"""Credit safeguards for Kane runs: balance pre-flight, run caps, infra circuit breaker, cost ledger.

Every Kane run in `rld check` and `rld gate` goes through Guard, which has the same call shape as a runner.
Env knobs: RLD_MIN_CREDITS (reserve, default 2000; 0 turns the balance check off), RLD_MAX_RUNS (per invocation,
default 12), RLD_MAX_CLAIM_RUNS (per claim, default 4). Only numbers and env var names are ever logged.
"""
from __future__ import annotations

import fcntl
import functools
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import kane

DEFAULT_MIN_CREDITS = 2000.0
DEFAULT_MAX_RUNS = 12
DEFAULT_MAX_CLAIM_RUNS = 4
INFRA_STREAK = 3
CREDITS_EXHAUSTED = "infra_error.credits_exhausted"


class InfraError(RuntimeError):
    """Kane or the box is broken (or the reserve is hit): stop the suite, exit 4."""


class RunCapReached(RuntimeError):
    """The per-invocation Kane run cap was hit."""


def _env_num(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def min_credits() -> float:
    return _env_num("RLD_MIN_CREDITS", DEFAULT_MIN_CREDITS)


def max_runs() -> int:
    return max(1, int(_env_num("RLD_MAX_RUNS", DEFAULT_MAX_RUNS)))


def max_claim_runs() -> int:
    return max(1, int(_env_num("RLD_MAX_CLAIM_RUNS", DEFAULT_MAX_CLAIM_RUNS)))


def read_balance() -> float:
    """`kane-cli balance` prints 'Available credits: 9999.9634'. Free, read-only."""
    exe = shutil.which("kane-cli") or os.path.expanduser("~/workspace/.npm-global/bin/kane-cli")
    try:
        p = subprocess.run([exe, "balance"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise InfraError(f"cannot read the Kane balance: {type(e).__name__}") from e
    m = re.search(r"Available credits:\s*(-?[\d,]*\.?\d+)", p.stdout or "")
    if not m:
        raise InfraError(f"cannot read the Kane balance (kane-cli balance exit {p.returncode})")
    return float(m.group(1).replace(",", ""))


def infra_like(run: kane.KaneRun) -> bool:
    return run.exit_code == 2 or run.reason_code.startswith("infra_error") or not run.has_run_end


class Guard:
    """Wraps a runner. Enforces reserve, run cap and infra streak; tracks runs, credits, balance."""

    def __init__(self, runner, balance_fn=None, reserve: float | None = None, cap: int | None = None,
                 streak_limit: int = INFRA_STREAK):
        self.runner, self.balance_fn = runner, balance_fn
        self.reserve = min_credits() if reserve is None else reserve
        self.cap = max_runs() if cap is None else cap
        self.streak_limit = streak_limit
        self.runs, self.credits, self.streak = 0, 0.0, 0
        self._fresh = False  # balance was just read by preflight(): skip a second read before run 1
        self.balance_before: float | None = None
        self.balance_after: float | None = None

    def _balance(self) -> float | None:
        if not self.balance_fn:
            return None
        try:
            bal = self.balance_fn()
        except InfraError:
            if self.reserve > 0:
                raise  # cannot prove the reserve is safe: fail closed
            return None
        if self.balance_before is None:
            self.balance_before = bal
        return bal

    def preflight(self) -> None:
        bal = self._balance()
        self._fresh = True
        if bal is not None and self.reserve > 0 and bal < self.reserve:
            raise InfraError(f"balance {bal:g} is below the reserve {self.reserve:g}; Kane was not run "
                             f"(lower RLD_MIN_CREDITS to override, e.g. on demo day)")

    def __call__(self, obj, url, outdir, label, timeout):
        if self.runs >= self.cap:
            raise RunCapReached(f"run cap {self.cap} reached (RLD_MAX_RUNS)")
        if self._fresh:
            self._fresh = False
        else:
            self.preflight()
            self._fresh = False
        self.runs += 1
        run = self.runner(obj, url, outdir, label, timeout)
        self.credits += run.credits or 0
        if run.reason_code == CREDITS_EXHAUSTED:
            raise InfraError("Kane says credits are exhausted; stopped the suite")
        self.streak = self.streak + 1 if infra_like(run) else 0
        if self.streak >= self.streak_limit:
            raise InfraError(f"{self.streak} Kane runs in a row returned no result (infra); stopped the suite")
        return run

    def close(self) -> None:
        """Read the balance once more for the ledger (only if Kane ran)."""
        if self.runs and self.balance_fn:
            try:
                self.balance_after = self.balance_fn()
            except InfraError:
                self.balance_after = None


def locked(fn):
    """One rld Kane run at a time per checkout (flock on .rld/run.lock). A second one exits 4 and spends nothing."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        Path(".rld").mkdir(exist_ok=True)
        f = open(".rld/run.lock", "w")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            print("rld: another rld check/gate is already running here; not starting a second one", file=sys.stderr)
            return 4
        try:
            return fn(*a, **k)
        finally:
            f.close()
    return wrapper


def make_guard(runner, default_runner, balance_fn=None) -> Guard:
    """The real balance reader is used only with the real runner; a fake runner stays offline unless a
    balance_fn is given."""
    if balance_fn is None and runner is default_runner:
        balance_fn = read_balance
    return Guard(runner, balance_fn)


def log_costs(path: str | Path, cmd: str, g: Guard, note: str = "") -> None:
    """Append one ledger line to docs/COSTS.md (only if Kane ran and the docs folder exists)."""
    p = Path(path)
    if not g.runs or not p.parent.is_dir():
        return
    b0, b1 = g.balance_before, g.balance_after
    bal = "balance unknown" if b0 is None or b1 is None else f"balance {b0:.2f} -> {b1:.2f} (drop {b0 - b1:.2f})"
    head = "" if p.exists() and "## Run ledger" in p.read_text() else "\n## Run ledger (written by rld)\n\n"
    with p.open("a") as f:
        f.write(f"{head}- {time.strftime('%Y-%m-%d %H:%M')} {cmd}: {g.runs} Kane runs, "
                f"{g.credits:.1f} credits by run_end, {bal}{'; ' + note if note else ''}\n")
