import json

from rld import gate, report


def test_headline():
    r = lambda v: {"verdict": v}  # noqa: E731
    h = report.headline([r("VERIFIED")] * 5 + [r("FALSE_CLAIM")] * 2)[0]
    assert h == "5 of 7 claims are true. This README is wrong in 2 places."
    assert "told the truth" in report.headline([r("VERIFIED")])[0]


def test_changed_since():
    prev = {"results": [{"id": "c01", "verdict": "FALSE_CLAIM", "readme_quote": "q1"},
                        {"id": "c02", "verdict": "VERIFIED", "readme_quote": "q2"}]}
    new = [{"id": "c01", "verdict": "VERIFIED", "readme_quote": "q1"}]
    out = report.changed_since(prev, new)
    assert "c01 FALSE_CLAIM to VERIFIED" in out and any("c02 removed" in x for x in out)


def test_order_failed_first_and_hint():
    claims = [{"id": "c01"}, {"id": "c02"}, {"id": "c03"}]
    prev = {"c03": {"verdict": "FALSE_CLAIM"}}
    assert [c["id"] for c in gate.order_claims(claims, prev, True)] == ["c03", "c01", "c02"]
    assert [c["id"] for c in gate.order_claims(claims, prev, False)] == ["c01", "c02", "c03"]
    r = {"fix_hint": "change the code in demo-app/ so the claim is true"}
    gate.retarget_hint(r, "tests/gate/")
    assert "tests/gate/" in r["fix_hint"]


def test_render_without_screenshots(tmp_path):
    doc = {"url": "http://x/", "readme": "R.md", "total_credits": 1, "results": [
        {"id": "c01", "verdict": "FALSE_CLAIM", "readme_line": 3, "readme_quote": "A <b>claim</b>", "expect": {"a": "1"},
         "observed": {}, "attempts": [], "credits": 1}]}
    idx = report.build(doc, tmp_path)
    t = idx.read_text()
    assert "False claim" in t and "&lt;b&gt;claim" in t and "No screenshots" in t
    assert json.loads((tmp_path / "history").glob("*.json").__next__().read_text())["results"]
