import json
from pathlib import Path

from rld import kane

FX = Path(__file__).parent / "fixtures"


def write(tmp_path, lines):
    p = tmp_path / "run.ndjson"
    p.write_text("\n".join(json.dumps(x) if not isinstance(x, str) else x for x in lines) + "\n")
    return p


def run_end(**kw):
    return {"type": "run_end", **kw}


# --- real fixtures ---------------------------------------------------------

def test_fixture_pass_5step_exit0_no_test_url():
    r = kane.parse(FX / "pass_5step_upload_failed.ndjson", 0)
    assert r.status == "passed" and r.cli_version == "0.10.4"
    assert r.credits == 22.612025 and r.duration == 94.3
    assert r.final_state["heading"] == "Checkboxes"
    assert r.test_url is None
    d = kane.decide(r)
    assert d.outcome == kane.PASS_WARN and d.warnings


def test_fixture_pass_15step_bifurcated():
    r = kane.parse(FX / "pass_15step_bifurcated.ndjson", 0)
    assert r.status == "passed" and r.test_url
    assert r.final_state["delete_count"] == "1"
    assert abs(r.credits - 63.86382) < 1e-6
    assert kane.decide(r).outcome == kane.PASS


def test_fixture_failed_assertion():
    r = kane.parse(FX / "fail_assertion.ndjson", 1)
    assert r.status == "failed"
    assert r.reason_code == "assertion_error.final_verification"
    assert r.final_state == {}
    assert any(s.status == "failed" for s in r.steps)
    assert kane.decide(r).outcome == kane.ASSERT_FAIL


def test_fixtures_have_no_home_paths():
    for f in FX.glob("*.ndjson"):
        t = f.read_text()
        assert "/home/hatch" not in t and "/dashboard/share/US_" not in t


# --- decision table ---------------------------------------------------------

def test_exit1_passed_upload_failed(tmp_path):
    p = write(tmp_path, [run_end(status="passed")])
    d = kane.decide(kane.parse(p, 1))
    assert d.outcome == kane.PASS_WARN


def test_exit2_is_infra_abort(tmp_path):
    p = write(tmp_path, [{"type": "stream_start", "cli_version": "0.10.4"}])
    d = kane.decide(kane.parse(p, 2))
    assert d.outcome == kane.INFRA and d.abort_suite


def test_exit2_even_with_run_end(tmp_path):
    p = write(tmp_path, [run_end(status="failed")])
    assert kane.decide(kane.parse(p, 2)).abort_suite


def test_exit3_retry_then_inconclusive(tmp_path):
    p = write(tmp_path, [run_end(status="failed")])
    r = kane.parse(p, 3)
    d1 = kane.decide(r, attempt=1)
    assert d1.outcome == kane.TIMEOUT and d1.retry
    d2 = kane.decide(r, attempt=2)
    assert d2.outcome == kane.INCONCLUSIVE and not d2.retry


def test_infra_error_reason_code_continues(tmp_path):
    p = write(tmp_path, [run_end(status="failed", reason_code="infra_error.screenshot_failed")])
    d = kane.decide(kane.parse(p, 1))
    assert d.outcome == kane.INCONCLUSIVE and not d.abort_suite


def test_infra_error_even_when_exit0(tmp_path):
    p = write(tmp_path, [run_end(status="passed", reason_code="infra_error.x", test_url="u")])
    assert kane.decide(kane.parse(p, 0)).outcome == kane.INCONCLUSIVE


def test_missing_run_end(tmp_path):
    p = write(tmp_path, [{"type": "stream_start"}, {"step": "2", "status": "done"}])
    r = kane.parse(p, 1)
    assert not r.has_run_end
    assert kane.decide(r).outcome == kane.INCONCLUSIVE


def test_missing_file(tmp_path):
    r = kane.parse(tmp_path / "nope.ndjson", 1)
    assert kane.decide(r).outcome == kane.INCONCLUSIVE


# --- parser robustness ------------------------------------------------------

def test_last_run_end_wins_and_trailing_junk_ignored(tmp_path):
    p = write(tmp_path, [
        run_end(status="failed", credits_consumed=1),
        run_end(status="passed", credits_consumed=2, test_url="u"),
        "stderr hint: not json",
        {"type": "warning", "code": "late"},
    ])
    r = kane.parse(p, 0)
    assert r.status == "passed" and r.credits == 2 and r.bad_lines == 1
    assert kane.decide(r).outcome == kane.PASS


def test_credits_fallback_to_docs_name(tmp_path):
    p = write(tmp_path, [run_end(status="passed", credits=3.5, test_url="u")])
    assert kane.parse(p, 0).credits == 3.5


def test_exit0_but_failed_is_inconclusive(tmp_path):
    p = write(tmp_path, [run_end(status="failed")])
    assert kane.decide(kane.parse(p, 0)).outcome == kane.INCONCLUSIVE


def test_optional_fields_absent(tmp_path):
    p = write(tmp_path, [run_end(status="failed")])
    r = kane.parse(p, 1)
    assert r.credits is None and r.final_state == {} and r.test_url is None
