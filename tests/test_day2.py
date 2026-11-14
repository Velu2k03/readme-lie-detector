import json
from pathlib import Path

import pytest

from rld import check, classify, extract, kane, objective

README = """# Demo
1. The page heading says "Welcome to Hati".
2. Clicking Add shows 3 items.
3. Loads instantly.
"""

CLAIM = {"id": "c01", "readme_line": 2, "readme_quote": 'The page heading says "Welcome to Hati".', "rank": 1,
         "setup": ["Look at the page"], "action": "Read the main heading",
         "assertions": ["the heading says 'Welcome to Hati'"], "store_name": "heading",
         "store_what": "the main heading text", "expect": {"heading": "Welcome to Hati"}}


def test_build_shape():
    o = objective.build(CLAIM, "http://x/")
    assert o.startswith("Go to http://x/.") and o.endswith("as 'heading'.") and "Assert the heading says" in o


def test_validate_rejects_non_readme_literal_and_selectors_and_four_asserts():
    bad = dict(CLAIM, expect={"heading": "Welcome to Somewhere"})
    with pytest.raises(objective.ObjectiveError):
        objective.validate_claim(bad, README)
    with pytest.raises(objective.ObjectiveError):
        objective.validate_claim(dict(CLAIM, action="Click #submit-btn now"), README)
    with pytest.raises(objective.ObjectiveError):
        objective.build(dict(CLAIM, assertions=["a", "b", "c", "d"]), "u")
    objective.validate_claim(CLAIM, README)


def test_rewrite_guard():
    ok = dict(CLAIM, setup=["Open the home page first"], action="Find the large title")
    objective.check_rewrite(CLAIM, ok)
    for bad in (dict(CLAIM, expect={"heading": "Hello"}),
                dict(CLAIM, assertions=[]),
                dict(CLAIM, assertions=["the heading says something like Welcome"]),
                dict(CLAIM, action="Read it; expected is 'Welcome'", assertions=["x"])):
        with pytest.raises(objective.ObjectiveError):
            objective.check_rewrite(CLAIM, bad)


def test_rewrite_rejects_model_touching_assertions():
    fake = lambda p, s: {"setup": ["a"], "action": "b", "assertions": ["softer"]}  # noqa: E731
    with pytest.raises(objective.ObjectiveError):
        objective.rewrite(CLAIM, "u", "o", [], "p", ask_json=fake)


def test_check_expect_normalizes():
    assert objective.check_expect({"expect": {"t": "$1,000.00"}}, {"t": " 1,000.00 "}) == []
    assert objective.check_expect({"expect": {"t": "5"}}, {"t": "6"})
    assert objective.check_expect({"expect": {"t": "5"}}, {})


def test_check_expect_list_spacing():
    ok = lambda e, o: objective.check_expect({"expect": {"t": e}}, {"t": o}) == []
    assert ok("333.34, 333.33, 333.33", "333.34,333.33,333.33")
    assert ok("500.01, 300.00 and 200.00", "500.01,300.00,200.00")
    assert not ok("333.34, 333.33", "333.34,333.43")
    assert not ok("1,000.00", "1000.00")


def test_check_expect_number_words():
    ok = lambda e, o: objective.check_expect({"expect": {"t": e}}, {"t": o}) == []
    assert ok("two", "2")
    assert not ok("two", "3")
    assert not ok("one hundred", "100")


def test_extract_lock_skips_llm_when_hash_same(tmp_path):
    rd = tmp_path / "R.md"; rd.write_text(README)
    calls = []
    def fake(p, s):
        calls.append(1)
        return {"claims": [CLAIM, dict(CLAIM, id="c02", expect={"heading": "Nope"})],
                "not_verifiable": [{"readme_line": 3, "quote": "Loads instantly.", "reason": "speed"}]}
    lock = tmp_path / "l.json"
    l1, ex1 = extract.load_lock_or_extract(rd, lock, fake)
    l2, ex2 = extract.load_lock_or_extract(rd, lock, fake)
    assert ex1 and not ex2 and len(calls) == 1
    assert l1["readme_sha256"] == extract.sha256(README)
    assert [c["id"] for c in l2["claims"]] == ["c01"]            # c02 rejected: literal not in README
    assert any("rejected" in x["reason"] for x in l2["not_verifiable"])
    rd.write_text(README + "x")
    _, ex3 = extract.load_lock_or_extract(rd, lock, fake)
    assert ex3 and len(calls) == 2


FX = Path(__file__).parent / "fixtures"


def test_classify_bad_test_needs_quote():
    run = kane.parse(FX / "fail_assertion.ndjson", 1)
    quote = next(s.remark for s in run.steps if s.status == "failed")
    good = classify.classify(CLAIM, "o", run, [], ask_json=lambda p, s: {"label": "bad_test", "evidence": quote, "reason": "r"})
    assert good.label == "bad_test"
    bad = classify.classify(CLAIM, "o", run, [], ask_json=lambda p, s: {"label": "bad_test", "evidence": "made up", "reason": "r"})
    assert bad.label == "unproven"
    fc = classify.classify(CLAIM, "o", run, [], ask_json=lambda p, s: {"label": "false_claim", "evidence": "", "reason": "r"})
    assert fc.label == "false_claim"


def _runner_from(fixtures):
    it = iter(fixtures)
    def runner(obj, url, outdir, label, timeout):
        name, code = next(it)
        return kane.parse(FX / name, code)
    return runner


def test_loop_verified_and_false_claim_and_exit_codes(tmp_path, monkeypatch):
    rd = tmp_path / "R.md"; rd.write_text(README)
    c1 = dict(CLAIM, id="c01", expect={"heading": "Checkboxes"}, readme_quote="Welcome to Hati", assertions=["x"])
    c2 = dict(CLAIM, id="c02")
    lock = tmp_path / "l.json"
    lock.write_text(json.dumps({"readme_sha256": extract.sha256(README), "claims": [c1, c2], "not_verifiable": []}))
    runner = _runner_from([("pass_5step_upload_failed.ndjson", 0), ("fail_assertion.ndjson", 1)])
    ask = lambda p, s: {"label": "false_claim", "evidence": "", "reason": "heading differs", "fix_hint": "fix it"}  # noqa: E731
    monkeypatch.chdir(tmp_path)
    code = check.check("http://x", str(rd), str(tmp_path / "out"), str(lock), runner=runner, ask_json=ask)
    # classify.ask_json default is llm; patch via monkeypatch of module-level default
    res = json.loads((tmp_path / "out/results.json").read_text())
    assert code == 1
    assert [r["verdict"] for r in res["results"]] == ["VERIFIED", "FALSE_CLAIM"]


def test_exit_code_table():
    r = lambda v: {"verdict": v}  # noqa: E731
    assert check.exit_code([r("VERIFIED")], False) == 0
    assert check.exit_code([r("VERIFIED"), r("INCONCLUSIVE")], False) == 3
    assert check.exit_code([r("STALE_DOC"), r("INCONCLUSIVE")], False) == 1
    assert check.exit_code([], True) == 4
