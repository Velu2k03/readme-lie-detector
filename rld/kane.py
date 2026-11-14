"""Parse kane-cli --agent NDJSON output and turn it into a decision.

Field names follow what kane-cli 0.10.4 really emits (see tests/fixtures):
run_end carries `credits_consumed` (the docs say `credits`; both are read).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# decide() outcomes
PASS = "PASS"                  # passed, upload fine
PASS_WARN = "PASS_WARN"        # passed, but no test_url (upload failed); verdict stands
ASSERT_FAIL = "ASSERT_FAIL"    # Kane ran and an assertion failed; classify next
INFRA = "INFRA"                # exit 2: auth/config/Chrome broken; abort the suite
TIMEOUT = "TIMEOUT"            # exit 3: retry once with a longer timeout
INCONCLUSIVE = "INCONCLUSIVE"  # cannot judge this claim; continue with the others


@dataclass
class Step:
    step: str
    status: str
    remark: str = ""


@dataclass
class KaneRun:
    exit_code: int
    run_end: dict[str, Any] | None = None
    cli_version: str | None = None
    steps: list[Step] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    flows: list[Any] = field(default_factory=list)
    bad_lines: int = 0

    @property
    def has_run_end(self) -> bool:
        return self.run_end is not None

    def _get(self, key: str, default: Any = None) -> Any:
        return (self.run_end or {}).get(key, default)

    @property
    def status(self) -> str | None:
        return self._get("status")

    @property
    def reason_code(self) -> str:
        return self._get("reason_code") or ""

    @property
    def credits(self) -> float | None:
        v = self._get("credits_consumed")
        if v is None:
            v = self._get("credits")
        return float(v) if isinstance(v, (int, float)) else None

    @property
    def duration(self) -> float | None:
        v = self._get("duration")
        return float(v) if isinstance(v, (int, float)) else None

    @property
    def final_state(self) -> dict[str, Any]:
        v = self._get("final_state")
        return v if isinstance(v, dict) else {}

    @property
    def test_url(self) -> str | None:
        return self._get("test_url")

    @property
    def one_liner(self) -> str:
        return self._get("one_liner") or ""

    @property
    def session_dir(self) -> str | None:
        return self._get("session_dir")


@dataclass
class Decision:
    outcome: str
    reason: str
    abort_suite: bool = False
    retry: bool = False
    warnings: list[str] = field(default_factory=list)


def parse(ndjson_path: str | Path, exit_code: int) -> KaneRun:
    """Read an NDJSON file. Uses the LAST run_end line, never tail -1."""
    run = KaneRun(exit_code=exit_code)
    p = Path(ndjson_path)
    text = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            run.bad_lines += 1
            continue
        if not isinstance(d, dict):
            run.bad_lines += 1
            continue
        t = d.get("type")
        if t == "run_end":
            run.run_end = d  # keep overwriting: last one wins
        elif t == "stream_start":
            run.cli_version = d.get("cli_version")
        elif t == "bifurcation":
            flows = d.get("flows")
            if isinstance(flows, list):
                run.flows = flows
        elif t == "warning":
            run.warnings.append(d)
        elif t is None and "step" in d:
            run.steps.append(Step(str(d["step"]), str(d.get("status", "")), str(d.get("remark", ""))))
    return run


def decide(run: KaneRun, attempt: int = 1) -> Decision:
    """Decision table, plan section 2.

    attempt is 1 for the first try; a second exit-3 becomes INCONCLUSIVE.
    """
    code = run.exit_code
    if code == 2:
        return Decision(INFRA, "exit 2: auth, config or Chrome is broken", abort_suite=True)
    if code == 3:
        if attempt <= 1:
            return Decision(TIMEOUT, "exit 3: timeout or cancelled; retry once with a longer timeout", retry=True)
        return Decision(INCONCLUSIVE, "exit 3 again after retry")
    if run.reason_code.startswith("infra_error"):
        return Decision(INCONCLUSIVE, f"infra error ({run.reason_code}); continue with other claims")
    if not run.has_run_end:
        return Decision(INCONCLUSIVE, "no run_end line in output (infra); continue with other claims")

    status = run.status
    if status == "passed" and code in (0, 1):
        warns = [] if run.test_url else ["no_test_url: upload failed, verdict stands"]
        if warns:
            return Decision(PASS_WARN, f"passed (exit {code}) without test_url", warnings=warns)
        return Decision(PASS, "passed")
    if status == "failed" and code == 1:
        return Decision(ASSERT_FAIL, run.reason_code or "run failed")
    return Decision(INCONCLUSIVE, f"unexpected combination: exit {code}, status {status!r}")
