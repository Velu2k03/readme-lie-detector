"""rld check: extract (or load lock), run one Kane objective per claim, classify, rewrite, write results.json."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from . import classify as clf
from . import extract, kane, objective

RUN_SCRIPT = os.environ.get("RLD_RUN_SCRIPT", os.path.expanduser("~/workspace/tools/kane-smoke/run-kane.sh"))
CHROME = os.path.expanduser("~/.cache/puppeteer/chrome/linux-155.0.8059.39/chrome-linux64/chrome")
TIMEOUT, TIMEOUT_RETRY = 180, 270
MAX_REWRITES = 2

VERIFIED, FALSE_CLAIM, STALE_DOC, INCONCLUSIVE, NOT_VERIFIABLE = (
    "VERIFIED", "FALSE_CLAIM", "STALE_DOC", "INCONCLUSIVE", "NOT_VERIFIABLE")
FIX_HINTS = {
    FALSE_CLAIM: "change the code so the README claim is true; do not edit the claim",
    STALE_DOC: "the feature works; update the README line to describe the app correctly",
}


class InfraError(RuntimeError):
    pass


def run_kane(obj: str, url: str, outdir: Path, label: str, timeout: int) -> kane.KaneRun:
    """One kane-cli run via the VM run script (proxy + Chrome for Testing + CDP)."""
    outdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CHROME_BIN=os.environ.get("CHROME_BIN", CHROME))
    subprocess.run(["bash", RUN_SCRIPT, str(outdir), label, str(timeout), url, obj],
                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout + 240)
    ec_file = outdir / f"{label}.exit"
    code = int(ec_file.read_text().strip()) if ec_file.exists() else 2
    return kane.parse(outdir / f"{label}.ndjson", code)


def _attempt_record(n, obj, run, dec, note=""):
    return {"attempt": n, "objective": obj, "exit_code": run.exit_code, "status": run.status,
            "decision": dec.outcome, "reason": dec.reason, "credits": run.credits, "duration": run.duration,
            "test_url": run.test_url, "note": note}


def run_claim(claim: dict, url: str, runs_dir: Path, confirm: bool, runner=run_kane, ask_json=None) -> dict:
    cur = dict(claim)
    attempts: list[dict] = []
    credits = 0.0
    n = 0
    rewrites = 0
    confirmed = False
    last_run = None
    while True:
        n += 1
        obj = objective.build(cur, url)
        label = f"{claim['id']}-a{n}"
        run = runner(obj, url, runs_dir, label, TIMEOUT)
        dec = kane.decide(run, 1)
        if dec.outcome == kane.TIMEOUT:
            credits += run.credits or 0
            attempts.append(_attempt_record(n, obj, run, dec, "timeout; retrying with longer timeout"))
            n += 1
            run = runner(obj, url, runs_dir, f"{claim['id']}-a{n}", TIMEOUT_RETRY)
            dec = kane.decide(run, 2)
        credits += run.credits or 0
        last_run = run
        if dec.outcome == kane.INFRA:
            attempts.append(_attempt_record(n, obj, run, dec))
            raise InfraError(f"{claim['id']}: {dec.reason}")
        if dec.outcome == kane.INCONCLUSIVE:
            attempts.append(_attempt_record(n, obj, run, dec))
            return _result(claim, INCONCLUSIVE, run, attempts, credits, cur, reason=dec.reason)

        mism: list[str] = []
        failed = dec.outcome == kane.ASSERT_FAIL
        if not failed:
            mism = objective.check_expect(cur, run.final_state)
            failed = bool(mism)
        if not failed:
            attempts.append(_attempt_record(n, obj, run, dec, "passed; stored values match the README"))
            return _result(claim, VERIFIED, run, attempts, credits, cur, observed=run.final_state)

        c = clf.classify(cur, obj, run, mism, ask_json)
        attempts.append(_attempt_record(n, obj, run, dec, f"classified {c.label}: {c.reason}" +
                                        (f" | mismatch {mism}" if mism else "")))
        if c.label == "bad_test":
            if rewrites >= MAX_REWRITES:
                return _result(claim, INCONCLUSIVE, run, attempts, credits, cur,
                               reason="still a bad test after two rewrites", cls=c)
            try:
                cur = objective.rewrite(cur, url, obj, [s.remark for s in run.steps], c.evidence, ask_json)
                rewrites += 1
                attempts[-1]["note"] += " -> rewritten"
                continue
            except objective.ObjectiveError as e:
                attempts[-1]["note"] += f" -> rewrite rejected: {e}"
                return _result(claim, INCONCLUSIVE, run, attempts, credits, cur, reason=f"rewrite rejected: {e}", cls=c)
        if c.label in ("false_claim", "stale_doc"):
            if confirm and not confirmed:
                confirmed = True
                attempts[-1]["note"] += " -> confirm re-run"
                continue
            verdict = FALSE_CLAIM if c.label == "false_claim" else STALE_DOC
            return _result(claim, verdict, run, attempts, credits, cur, observed=run.final_state, cls=c, mism=mism)
        return _result(claim, INCONCLUSIVE, run, attempts, credits, cur, reason=c.reason, cls=c)


def _result(claim, verdict, run, attempts, credits, cur, observed=None, reason="", cls=None, mism=None):
    r = {"id": claim["id"], "verdict": verdict, "readme_line": claim.get("readme_line"),
         "readme_quote": claim.get("readme_quote"), "expect": claim.get("expect"),
         "observed": observed if observed is not None else run.final_state,
         "one_liner": run.one_liner, "reason": reason or (run.run_end or {}).get("reason"),
         "objective": attempts[-1]["objective"], "attempts": attempts, "credits": round(credits, 3),
         "duration": run.duration, "test_url": run.test_url, "session_dir": run.session_dir,
         "step_remarks": [f"[{s.step} {s.status}] {s.remark}" for s in run.steps if s.remark]}
    if mism:
        r["mismatch"] = mism
    if cls:
        r["classification"] = {"label": cls.label, "evidence": cls.evidence, "reason": cls.reason}
    if verdict in FIX_HINTS:
        r["fix_hint"] = FIX_HINTS[verdict] + (f" ({cls.fix_hint})" if cls and cls.fix_hint else "")
    return r


def exit_code(results: list[dict], infra: bool) -> int:
    if infra:
        return 4
    vs = {r["verdict"] for r in results}
    if vs & {FALSE_CLAIM, STALE_DOC}:
        return 1
    if INCONCLUSIVE in vs:
        return 3
    return 0


def check(url: str, readme: str, out: str = "report", lock: str = "claims.lock.json", confirm: bool = False,
          runner=run_kane, ask_json=None) -> int:
    outd = Path(out)
    outd.mkdir(parents=True, exist_ok=True)
    runs_dir = Path(".rld/runs") / time.strftime("%Y%m%d-%H%M%S")
    lk, extracted = extract.load_lock_or_extract(readme, lock, ask_json)
    results, infra, err = [], False, None
    for claim in lk["claims"]:
        try:
            results.append(run_claim(claim, url, runs_dir, confirm, runner, ask_json))
        except InfraError as e:
            infra, err = True, str(e)
            break
    for nv in lk.get("not_verifiable", []):
        results.append({"id": f"nv{len(results)+1}", "verdict": NOT_VERIFIABLE, "readme_line": nv.get("readme_line"),
                        "readme_quote": nv.get("quote"), "reason": nv.get("reason")})
    code = exit_code([r for r in results if r["verdict"] != NOT_VERIFIABLE], infra)
    doc = {"url": url, "readme": str(readme), "readme_sha256": lk["readme_sha256"], "extracted_now": extracted,
           "exit_code": code, "infra_error": err, "total_credits": round(sum(r.get("credits", 0) for r in results), 3),
           "results": results}
    (outd / "results.json").write_text(json.dumps(doc, indent=2) + "\n")
    return code
