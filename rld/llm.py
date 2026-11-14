"""LLM backend: headless Claude Code (`claude -p`) on the Pro plan. No API key, no spend.

Flags (checked with `claude --help`, v2.1.319):
  -p                       non-interactive
  --output-format json     one JSON object with `result` and `is_error`
  --tools ""               no tools: the model only answers
  --disable-slash-commands no skills
  --no-session-persistence nothing saved to disk
Runs from a temp dir so no project CLAUDE.md is loaded.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile

CLAUDE = os.environ.get("RLD_CLAUDE", os.path.expanduser("~/.local/bin/claude"))
MODEL = os.environ.get("RLD_MODEL", "sonnet")


class LLMError(RuntimeError):
    pass


class LLMLimit(LLMError):
    """Usage limit hit. Carries the exact message so it can be reported."""


def _cmd(system: str) -> list[str]:
    return [CLAUDE, "-p", "--output-format", "json", "--tools", "", "--disable-slash-commands",
            "--no-session-persistence", "--model", MODEL, "--system-prompt", system]


def ask(prompt: str, system: str, timeout: int = 300) -> str:
    with tempfile.TemporaryDirectory() as cwd:
        p = subprocess.run(_cmd(system), input=prompt, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd, env=dict(os.environ, RLD_HOOK="off"))  # never let a nested turn fire the Stop hook
    out = (p.stdout or "").strip()
    try:
        d = json.loads(out)
        text = str(d.get("result", ""))
        is_err = bool(d.get("is_error"))
    except json.JSONDecodeError:
        text, is_err = out, p.returncode != 0
    if is_err or p.returncode != 0:
        msg = (text or p.stderr or "").strip()
        if "limit" in msg.lower():
            raise LLMLimit(msg)
        raise LLMError(f"claude -p failed (rc={p.returncode}): {msg[:500]}")
    return text


def extract_json(text: str):
    """Pull the first JSON object out of a model reply (tolerates code fences)."""
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e <= s:
        raise LLMError("no JSON object in model reply")
    try:
        return json.loads(text[s:e + 1])
    except json.JSONDecodeError as ex:
        raise LLMError(f"bad JSON from model: {ex}") from ex


def ask_json(prompt: str, system: str, retries: int = 1):
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            return extract_json(ask(prompt, system))
        except LLMLimit:
            raise
        except LLMError as ex:
            last = ex
    raise LLMError(str(last))
