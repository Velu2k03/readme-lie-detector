"""Compile a claim into one Kane objective plus an expect map, and guard rewrites.

Fixed shape (plan section 2):
  Go to {url}. {setup...}. {action}. Assert {a1}. Assert {a2}. Store {what} as '{name}'.
Expected literals are copied from the README, never from the app.
"""
from __future__ import annotations

import re
from typing import Any

MAX_ASSERTIONS = 3
MAX_STEPS = 25


class ObjectiveError(ValueError):
    pass


def _sentence(s: str) -> str:
    s = " ".join(str(s).split()).strip()
    return s if s.endswith((".", "!", "?")) else s + "."


def norm(s: Any) -> str:
    """Normalize for comparison: whitespace and currency symbols out, case kept."""
    t = str(s)
    t = re.sub(r"[$€£₹₱]", "", t)
    return " ".join(t.split()).strip()


def build(claim: dict, url: str) -> str:
    """Build the objective string from a claim's parts."""
    setup = [x for x in claim.get("setup", []) if str(x).strip()]
    action = str(claim.get("action", "")).strip()
    asserts = [x for x in claim.get("assertions", []) if str(x).strip()]
    name = claim.get("store_name", "")
    what = claim.get("store_what", "")
    if not (action and asserts and name and what):
        raise ObjectiveError("claim needs action, assertions, store_name and store_what")
    if len(asserts) > MAX_ASSERTIONS:
        raise ObjectiveError(f"more than {MAX_ASSERTIONS} assertions")
    parts = [f"Go to {url}."]
    parts += [_sentence(s) for s in setup]
    parts.append(_sentence(action))
    parts += [_sentence("Assert " + re.sub(r"^assert\s+", "", a, flags=re.I)) for a in asserts]
    parts.append(f"Store {what.rstrip('.')} as '{name}'.")
    return " ".join(parts)


def validate_claim(claim: dict, readme_text: str) -> None:
    """Reject claims that break the plan rules. Raises ObjectiveError."""
    expect = claim.get("expect") or {}
    if not expect or not isinstance(expect, dict):
        raise ObjectiveError("expect map is empty")
    if claim.get("store_name") not in expect:
        raise ObjectiveError("store_name must be a key of expect")
    flat = norm(readme_text)
    for k, v in expect.items():
        if norm(v) not in flat:
            raise ObjectiveError(f"expect[{k}]={v!r} is not literal README text")
    steps = len(claim.get("setup", [])) + 1 + len(claim.get("assertions", [])) + 2
    if steps > MAX_STEPS:
        raise ObjectiveError(f"{steps} steps, more than {MAX_STEPS}")
    if re.search(r"(css|selector|xpath|#[\w-]+\s|\.[a-z][\w-]*\s*\{)", " ".join(
            [claim.get("action", "")] + list(claim.get("setup", [])) + list(claim.get("assertions", []))), re.I):
        raise ObjectiveError("objective mentions a selector; use visible labels")


def check_rewrite(old: dict, new: dict) -> None:
    """Rewrite guard. May change setup and action wording only.

    Rejects: changed expect, changed/removed/softened assertions, dropped expected literal.
    """
    if (new.get("expect") or None) != (old.get("expect") or None):
        raise ObjectiveError("rewrite changed expect")
    if new.get("store_name") != old.get("store_name"):
        raise ObjectiveError("rewrite changed store_name")
    if list(new.get("assertions", [])) != list(old.get("assertions", [])):
        raise ObjectiveError("rewrite changed or removed an assertion")
    text = norm(" ".join([new.get("action", "")] + list(new.get("setup", [])) + list(new.get("assertions", []))
                         + [new.get("store_what", "")]))
    for lit in _literals(old):
        if lit not in text:
            raise ObjectiveError(f"rewrite dropped expected literal {lit!r}")


def _literals(claim: dict) -> list[str]:
    """Literals that appeared in the old objective text AND in expect values."""
    old_text = norm(" ".join([claim.get("action", "")] + list(claim.get("setup", []))
                             + list(claim.get("assertions", []))))
    return [norm(v) for v in (claim.get("expect") or {}).values() if norm(v) in old_text]


def values_match(expected: Any, observed: Any) -> bool:
    return norm(expected) == norm(observed)


def check_expect(claim: dict, final_state: dict) -> list[str]:
    """Deterministic second judge. Returns a list of mismatch descriptions (empty = agree)."""
    bad = []
    for k, v in (claim.get("expect") or {}).items():
        if k not in final_state:
            bad.append(f"{k}: not stored (expected {v!r})")
        elif not values_match(v, final_state[k]):
            bad.append(f"{k}: expected {v!r}, observed {final_state[k]!r}")
    return bad


REWRITE_SYSTEM = """You fix a broken browser test. Kane (an AI browser agent) failed BEFORE reaching the claim,
for a test reason (wrong page, element not found, setup failed). Rewrite ONLY the navigation `setup` steps
and the `action` wording so Kane can get there. Use visible labels and text, never CSS selectors.
You MUST NOT change `assertions`, `expect`, `store_name`, `store_what`, and must keep every literal value.
Reply with one JSON object: {"setup": [...], "action": "..."} and nothing else."""


def rewrite(claim: dict, url: str, objective: str, steps: list[str], proof: str, ask_json=None) -> dict:
    """One LLM call to rewrite a bad test. Returns the new claim; raises ObjectiveError if the guard rejects it."""
    if ask_json is None:
        from .llm import ask_json as _aj
        ask_json = lambda p, s: _aj(p, s)  # noqa: E731
    import json
    prompt = (f"App URL: {url}\nREADME quote: {claim.get('readme_quote')}\n"
              f"Current claim parts:\n{json.dumps({k: claim.get(k) for k in ('setup', 'action', 'assertions', 'store_name', 'store_what', 'expect')}, indent=1)}\n"
              f"Objective Kane ran:\n{objective}\n\nKane step remarks:\n" + "\n".join(steps[-20:]) +
              f"\n\nWhy it was judged a bad test: {proof}\n")
    d = ask_json(prompt, REWRITE_SYSTEM)
    new = dict(claim)
    new["setup"] = [str(x) for x in d.get("setup", claim.get("setup", []))]
    new["action"] = str(d.get("action", claim.get("action", "")))
    for k in ("assertions", "expect", "store_name", "store_what"):  # model may not touch these
        if k in d and d[k] != claim.get(k):
            raise ObjectiveError(f"rewrite tried to change {k}")
    check_rewrite(claim, new)
    build(new, url)
    return new
