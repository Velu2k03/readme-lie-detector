"""Credit safeguards. Fake runners and fake balances only: no test here can spend a Kane credit."""
import inspect
import json
import os
import time
from pathlib import Path

import pytest

from rld import __main__ as cli
from rld import budget, check, classify, extract, gate, kane, llm, objective

FX = Path(__file__).parent / "fixtures"
README = "# Demo\nThe page heading says Checkboxes.\n"
BASE = {"readme_line": 2, "readme_quote": "The page heading says Checkboxes.", "rank": 1, "setup": ["Look"],
        "action": "Read the heading", "assertions": ["the heading says 'Checkboxes'"], "store_name": "heading",
        "store_what": "the heading", "expect": {"heading": "Checkboxes"}}


def claims(n):
    return [dict(BASE, id=f"c{i:02d}") for i in range(1, n + 1)]


class Counter:
    """Fake runner: counts calls, returns the given fixtures in turn (the last one repeats)."""

    def __init__(self, *seq):
        self.seq, self.calls = list(seq), 0

    def __call__(self, obj, url, outdir, label, timeout):
        i = min(self.calls, len(self.seq) - 1)
        self.calls += 1
        item = self.seq[i]
        return item if isinstance(item, kane.KaneRun) else kane.parse(FX / item[0], item[1])


PASS = ("pass_5step_upload_failed.ndjson", 0)
FAIL = ("fail_assertion.ndjson", 1)
NO_RESULT = kane.KaneRun(exit_code=1)  # no run_end line: infra-like
EXHAUSTED = kane.KaneRun(exit_code=1, run_end={"status": "failed", "reason_code": "infra_error.credits_exhausted",
                                              "credits_consumed": 0})
TIMEOUT = kane.KaneRun(exit_code=3)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """tmp cwd, a README + lock of N claims, an app dir; clear the RLD_* env knobs."""
    for k in ("RLD_MIN_CREDITS", "RLD_MAX_RUNS", "RLD_MAX_CLAIM_RUNS", "RLD_FORCE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "app").mkdir()
    (tmp_path / "app/index.html").write_text("v1")

    def setup(n=3):
        rd = tmp_path / "R.md"
        rd.write_text(README)
        lk = tmp_path / "l.json"
        lk.write_text(json.dumps({"readme_sha256": extract.sha256(README), "claims": claims(n), "not_verifiable": []}))
        return dict(url="http://x", readme=str(rd), out=str(tmp_path / "out"), lock=str(lk))

    return setup


def gate_kw(a):
    return dict(url=a["url"], readme=a["readme"], out=a["out"], lock=a["lock"], app_dir="app/")


# --- pre-flight balance check ---------------------------------------------------------------------------

def test_preflight_refuses_below_reserve_and_never_runs_kane(env, capsys):
    a, r = env(2), Counter(PASS)
    code = check.check(a["url"], a["readme"], a["out"], a["lock"], runner=r, balance_fn=lambda: 1999.0)
    assert code == 4 and r.calls == 0
    assert "below the reserve 2000" in capsys.readouterr().err
    assert not Path(a["out"], "results.json").exists()  # the last report is not clobbered


def test_preflight_passes_at_reserve_and_env_overrides(env, monkeypatch):
    a, r = env(1), Counter(PASS)
    assert check.check(a["url"], a["readme"], a["out"], a["lock"], runner=r, balance_fn=lambda: 2000.0) == 0
    monkeypatch.setenv("RLD_MIN_CREDITS", "50")
    r2 = Counter(PASS)
    assert check.check(a["url"], a["readme"], a["out"], a["lock"], runner=r2, balance_fn=lambda: 500.0) == 0
    assert r2.calls == 1


def test_unreadable_balance_fails_closed_unless_reserve_is_zero(env, monkeypatch):
    def broken():
        raise budget.InfraError("cannot read the Kane balance")
    a, r = env(1), Counter(PASS)
    assert check.check(a["url"], a["readme"], a["out"], a["lock"], runner=r, balance_fn=broken) == 4
    assert r.calls == 0
    monkeypatch.setenv("RLD_MIN_CREDITS", "0")
    assert check.check(a["url"], a["readme"], a["out"], a["lock"], runner=r, balance_fn=broken) == 0
    assert r.calls == 1


def test_balance_is_rechecked_before_every_run(env):
    a, r = env(3), Counter(PASS)
    bal = iter([2100.0, 2050.0, 1990.0, 1990.0])  # drops under the reserve before the 3rd run
    code = check.check(a["url"], a["readme"], a["out"], a["lock"], runner=r, balance_fn=lambda: next(bal))
    assert code == 4 and r.calls == 2


def test_read_balance_parses_kane_output(monkeypatch):
    class P:
        stdout, returncode = "Available credits: 9,999.9634\n", 0
    monkeypatch.setattr(budget.subprocess, "run", lambda *a, **k: P())
    assert budget.read_balance() == 9999.9634
    P.stdout = "boom"
    with pytest.raises(budget.InfraError):
        budget.read_balance()


# --- run caps -----------------------------------------------------------------------------------------

def test_invocation_cap_stops_and_reports_unrun_claims(env, monkeypatch, capsys):
    monkeypatch.setenv("RLD_MAX_RUNS", "2")
    a, r = env(5), Counter(PASS)
    code = check.check(a["url"], a["readme"], a["out"], a["lock"], runner=r, balance_fn=lambda: 9000.0)
    assert r.calls == 2 and code == 3  # green so far, but not everything ran: not exit 0
    assert "3 claim(s) not run" in capsys.readouterr().err
    assert json.loads(Path(a["out"], "results.json").read_text())["run_cap_hit"] is True


def test_default_caps():
    assert (budget.max_runs(), budget.max_claim_runs(), budget.min_credits()) == (12, 4, 2000.0)


def test_per_claim_cap_stops_a_bad_test_rewrite_loop(tmp_path, monkeypatch):
    bad = classify.Classification("bad_test", "q", "r", "")
    monkeypatch.setattr(classify, "classify", lambda *a, **k: bad)
    monkeypatch.setattr(objective, "rewrite", lambda cur, *a, **k: cur)
    r = Counter(FAIL)
    res = check.run_claim(claims(1)[0], "http://x", tmp_path, False, r)
    assert r.calls == 3 and "two rewrites" in res["reason"]  # MAX_REWRITES=2 is enforced: 1 + 2 = 3 runs
    r = Counter(FAIL)
    res = check.run_claim(claims(1)[0], "http://x", tmp_path, False, r, max_runs=2)
    assert r.calls == 2 and res["verdict"] == "INCONCLUSIVE" and "run cap (2)" in res["reason"]


def test_per_claim_cap_covers_timeout_retry_and_confirm(tmp_path, monkeypatch):
    r = Counter(TIMEOUT)
    res = check.run_claim(claims(1)[0], "http://x", tmp_path, False, r, max_runs=1)
    assert r.calls == 1 and res["verdict"] == "INCONCLUSIVE" and "cap" in res["reason"]
    r = Counter(TIMEOUT)
    check.run_claim(claims(1)[0], "http://x", tmp_path, False, r)
    assert r.calls == 2  # 1 + exactly one retry, then INCONCLUSIVE
    fc = classify.Classification("false_claim", "", "r", "")
    monkeypatch.setattr(classify, "classify", lambda *a, **k: fc)
    r = Counter(FAIL)
    res = check.run_claim(claims(1)[0], "http://x", tmp_path, True, r, max_runs=1)
    assert r.calls == 1 and res["verdict"] == "FALSE_CLAIM"  # the confirm re-run is skipped at the cap
    r = Counter(FAIL)
    check.run_claim(claims(1)[0], "http://x", tmp_path, True, r)
    assert r.calls == 2  # with room, confirm runs once


def test_worst_case_runs_per_claim_never_exceeds_default_cap(tmp_path, monkeypatch):
    # timeout-then-fail rewrite loop with confirm: would be 8 runs without the cap
    runs = [TIMEOUT, kane.parse(FX / FAIL[0], 1)] * 8
    bad = classify.Classification("bad_test", "q", "r", "")
    monkeypatch.setattr(classify, "classify", lambda *a, **k: bad)
    monkeypatch.setattr(objective, "rewrite", lambda cur, *a, **k: cur)
    r = Counter(*runs)
    check.run_claim(claims(1)[0], "http://x", tmp_path, True, r)
    assert r.calls <= 4


# --- circuit breaker ----------------------------------------------------------------------------------

def test_credits_exhausted_aborts_at_once(env):
    a, r = env(5), Counter(EXHAUSTED)
    code = check.check(a["url"], a["readme"], a["out"], a["lock"], runner=r, balance_fn=lambda: 9000.0)
    assert code == 4 and r.calls == 1


def test_three_infra_runs_in_a_row_abort_the_suite(env):
    a, r = env(6), Counter(NO_RESULT)
    code = check.check(a["url"], a["readme"], a["out"], a["lock"], runner=r, balance_fn=lambda: 9000.0)
    assert code == 4 and r.calls == 3


def test_a_good_run_resets_the_infra_streak(env):
    a, r = env(5), Counter(NO_RESULT, NO_RESULT, PASS, NO_RESULT, NO_RESULT)
    check.check(a["url"], a["readme"], a["out"], a["lock"], runner=r, balance_fn=lambda: 9000.0)
    assert r.calls == 5  # never 3 in a row


# --- gate defaults and fingerprint skip -------------------------------------------------------------

def test_gate_is_cheap_by_default(monkeypatch):
    sig = inspect.signature(gate.gate).parameters
    assert sig["failed_first"].default is True and sig["stop_on_red"].default is True
    seen = {}
    monkeypatch.setattr(cli.gt, "gate", lambda *a: seen.setdefault("a", a) and 0)
    cli.main(["gate", "--url", "u", "--readme", "r"])
    assert seen["a"][5:7] == (True, True)
    seen.clear()
    cli.main(["gate", "--url", "u", "--readme", "r", "--no-stop-on-red"])
    assert seen["a"][5:7] == (True, False)


def test_gate_stops_on_first_red_by_default(env, monkeypatch):
    fc = classify.Classification("false_claim", "", "r", "")
    monkeypatch.setattr(classify, "classify", lambda *a, **k: fc)
    a, r = env(4), Counter(FAIL)
    code = gate.gate(**gate_kw(a), runner=r, balance_fn=lambda: 9000.0)
    assert code == 1 and r.calls == 1


def test_gate_skips_when_nothing_changed_since_green(env, capsys):
    a = env(3)
    r = Counter(PASS)
    assert gate.gate(**gate_kw(a), runner=r, balance_fn=lambda: 9000.0) == 0 and r.calls == 3
    r2 = Counter(PASS)
    assert gate.gate(**gate_kw(a), runner=r2, balance_fn=lambda: 0.0) == 0  # skip happens before any balance read
    assert r2.calls == 0 and "no changes, gate skipped" in capsys.readouterr().out


def test_gate_reruns_when_build_or_readme_changes_or_forced(env, monkeypatch):
    a = env(2)
    gate.gate(**gate_kw(a), runner=Counter(PASS), balance_fn=lambda: 9000.0)
    Path("app/index.html").write_text("v2")  # build output changed
    r = Counter(PASS)
    gate.gate(**gate_kw(a), runner=r, balance_fn=lambda: 9000.0)
    assert r.calls == 2
    monkeypatch.setenv("RLD_FORCE", "1")
    r = Counter(PASS)
    gate.gate(**gate_kw(a), runner=r, balance_fn=lambda: 9000.0)
    assert r.calls == 2
    monkeypatch.delenv("RLD_FORCE")
    assert gate.app_fingerprint("app/", "h1") != gate.app_fingerprint("app/", "h2")  # README hash is in it
    assert gate.app_fingerprint("nope/", "h") is None  # unknown app: never skip


def test_gate_does_not_skip_after_a_red_run(env, monkeypatch):
    fc = classify.Classification("false_claim", "", "r", "")
    monkeypatch.setattr(classify, "classify", lambda *a, **k: fc)
    a = env(2)
    gate.gate(**gate_kw(a), runner=Counter(FAIL), balance_fn=lambda: 9000.0)
    r = Counter(FAIL)
    gate.gate(**gate_kw(a), runner=r, balance_fn=lambda: 9000.0)
    assert r.calls == 1  # the red claim is checked again (failed-first), nothing is skipped for it


def test_gate_resumes_after_cap_and_runs_only_the_unverified(env, monkeypatch):
    a = env(4)
    monkeypatch.setenv("RLD_MAX_RUNS", "2")
    r = Counter(PASS)
    assert gate.gate(**gate_kw(a), runner=r, balance_fn=lambda: 9000.0) == 3 and r.calls == 2
    r2 = Counter(PASS)
    assert gate.gate(**gate_kw(a), runner=r2, balance_fn=lambda: 9000.0) == 0
    assert r2.calls == 2  # c03 and c04 only; c01 and c02 were already verified on this build


def test_gate_infra_abort_keeps_previous_results_and_exit_4(env):
    a = env(3)
    r = Counter(EXHAUSTED)
    assert gate.gate(**gate_kw(a), runner=r, balance_fn=lambda: 9000.0) == 4 and r.calls == 1


# --- cost ledger --------------------------------------------------------------------------------------

def test_costs_ledger_line(env, tmp_path):
    a = env(2)
    bal = iter([5000.0, 5000.0, 4950.5, 4950.5])
    log = tmp_path / "docs/COSTS.md"
    log.write_text("# costs\n")
    check.check(a["url"], a["readme"], a["out"], a["lock"], runner=Counter(PASS), balance_fn=lambda: next(bal),
                costs_log=str(log))
    text = log.read_text()
    assert "## Run ledger" in text and "check: 2 Kane runs" in text
    assert "balance 5000.00 -> 4950.50 (drop 49.50)" in text


def test_costs_ledger_skips_when_no_runs_or_no_docs_dir(tmp_path):
    g = budget.Guard(Counter(PASS))
    budget.log_costs(tmp_path / "docs/COSTS.md", "gate", g)  # no runs: nothing written
    g.runs = 1
    budget.log_costs(tmp_path / "missing/COSTS.md", "gate", g)
    assert not (tmp_path / "missing").exists()


# --- loops outside the claim runner -----------------------------------------------------------------

def test_hung_run_script_is_killed_with_all_its_children(tmp_path, monkeypatch):
    script = tmp_path / "hang.sh"
    pidfile = tmp_path / "child.pid"
    script.write_text(f"#!/bin/bash\nsleep 60 &\necho $! > {pidfile}\nwait\n")
    monkeypatch.setattr(check, "RUN_SCRIPT", str(script))
    monkeypatch.setattr(check, "KILL_GRACE", 0)
    t = time.time()
    run = check.run_kane("obj", "http://x", tmp_path / "o", "c01-a1", 1)
    assert time.time() - t < 15 and run.exit_code == 2  # no exit file -> infra, the suite aborts
    pid = int(pidfile.read_text())
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)  # the orphaned child (stands in for kane-cli) is gone


def test_nested_claude_turn_cannot_fire_the_stop_hook(monkeypatch):
    seen = {}

    class P:
        stdout, stderr, returncode = json.dumps({"result": "{}", "is_error": False}), "", 0

    def fake(*a, **k):
        seen.update(k["env"])
        return P()
    monkeypatch.setattr(llm.subprocess, "run", fake)
    llm.ask("p", "s")
    assert seen["RLD_HOOK"] == "off"


def test_second_run_is_refused_while_one_is_active(env, capsys):
    a = env(1)

    class Reenter:
        calls = 0

        def __call__(self, obj, url, outdir, label, timeout):
            Reenter.calls += 1
            # a second gate started while this run is mid-flight must not reach Kane
            inner = Counter(PASS)
            assert gate.gate(**gate_kw(a), runner=inner, balance_fn=lambda: 9000.0) == 4
            assert inner.calls == 0
            return kane.parse(FX / PASS[0], 0)

    assert gate.gate(**gate_kw(a), runner=Reenter(), balance_fn=lambda: 9000.0) == 0
    assert "already running" in capsys.readouterr().err
    r = Counter(PASS)  # the lock is released afterwards
    Path("app/index.html").write_text("v9")
    assert gate.gate(**gate_kw(a), runner=r, balance_fn=lambda: 9000.0) == 0 and r.calls == 1
