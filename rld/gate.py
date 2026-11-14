"""rld gate: the cheap loop the Stop hook runs. Same claim runner as `rld check`, plus
--failed-first (claims that were red last time go first) and --stop-on-red (stop at the first red claim, so the
agent gets one failure per round). Claims not run this round keep their previous result, marked `carried`.
Exit codes: 0 all green, 1 a FALSE_CLAIM or STALE_DOC, 3 inconclusive only, 4 infra.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

from . import budget
from . import check as chk
from . import extract

RED = (chk.FALSE_CLAIM, chk.STALE_DOC)


def _previous(outd: Path) -> dict[str, dict]:
    try:
        d = json.loads((outd / "results.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {r["id"]: r for r in d.get("results", []) if r.get("verdict") != chk.NOT_VERIFIABLE}


def order_claims(claims: list[dict], prev: dict[str, dict], failed_first: bool) -> list[dict]:
    if not failed_first:
        return list(claims)
    red = [c for c in claims if prev.get(c["id"], {}).get("verdict") in RED + (chk.INCONCLUSIVE,)]
    return red + [c for c in claims if c not in red]


def retarget_hint(r: dict, app_dir: str) -> None:
    if r.get("fix_hint") and app_dir != "demo-app/":
        r["fix_hint"] = r["fix_hint"].replace("demo-app/", app_dir)


def app_fingerprint(app_dir: str, readme_sha: str) -> str | None:
    """sha256 over the README hash and the built app (app_dir/dist if it exists, else the app source)."""
    root = Path(app_dir)
    if not root.is_dir():
        return None
    base = root / "dist" if (root / "dist").is_dir() else root
    h = hashlib.sha256(readme_sha.encode())
    for f in sorted(base.rglob("*")):
        rel = f.relative_to(base)
        if f.is_file() and not ({"node_modules", ".git", "dist"} & set(rel.parts)):
            h.update(str(rel).encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def _load_fp(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


@budget.locked
def gate(url: str, readme: str, out: str = "report", lock: str = "claims.lock.json", app_dir: str = "demo-app/",
         failed_first: bool = True, stop_on_red: bool = True, confirm: bool = False,
         runner=chk.run_kane, ask_json=None, balance_fn=None, costs_log: str = "docs/COSTS.md",
         fp_file: str = ".rld/fingerprint.json") -> int:
    """failed_first and stop_on_red are ON by default, so a bare `rld gate` is the cheap one.
    A claim that was VERIFIED on the same README + build (fingerprint) is not re-run; if every claim is,
    the gate is skipped (no Kane runs). RLD_FORCE=1 ignores the fingerprint."""
    outd = Path(out)
    outd.mkdir(parents=True, exist_ok=True)
    runs_dir = Path(".rld/runs") / time.strftime("%Y%m%d-%H%M%S")
    lk, extracted = extract.load_lock_or_extract(readme, lock, ask_json)
    prev = _previous(outd) if lk["readme_sha256"] == _prev_hash(outd) else {}
    fp = app_fingerprint(app_dir, lk["readme_sha256"])
    fpf = Path(fp_file)
    state = _load_fp(fpf)
    same = fp is not None and state.get("fingerprint") == fp and os.environ.get("RLD_FORCE") != "1"
    skip = {i for i in state.get("verified", []) if prev.get(i, {}).get("verdict") == chk.VERIFIED} if same else set()
    todo = [c for c in order_claims(lk["claims"], prev, failed_first) if c["id"] not in skip]
    if not todo:
        print("no changes, gate skipped: README and app build are unchanged and every claim is already verified")
        return 0
    guard = budget.make_guard(runner, chk.run_kane, balance_fn)
    try:
        guard.preflight()
    except budget.InfraError as e:
        print(f"rld: {e}", file=sys.stderr)
        return 4   # nothing ran: leave the last report alone
    ran: dict[str, dict] = {}
    infra, err, capped = False, None, False
    for claim in todo:
        try:
            r = chk.run_claim(claim, url, runs_dir, confirm, guard, ask_json)
        except chk.InfraError as e:
            infra, err = True, str(e)
            break
        except budget.RunCapReached as e:
            capped = True
            print(f"rld: {e}; {len(todo) - len(ran)} claim(s) not run", file=sys.stderr)
            break
        retarget_hint(r, app_dir)
        ran[claim["id"]] = r
        if stop_on_red and r["verdict"] in RED:
            break
    results = []
    for c in lk["claims"]:
        if c["id"] in ran:
            results.append(ran[c["id"]])
        elif c["id"] in prev:
            results.append(dict(prev[c["id"]], carried=True))
    results += chk.nv_results(lk, len(results))
    code = chk.exit_code([r for r in results if r["verdict"] != chk.NOT_VERIFIABLE and not r.get("carried")], infra)
    if capped and code == 0:
        code = 3   # green so far, but not every claim ran
    chk.finish(url, readme, lk, extracted, results, code, err, outd,
               {"runs": guard.runs, "run_cap_hit": capped} if capped else None)
    if fp is not None:
        done = (skip if same else set()) | {i for i, r in ran.items() if r["verdict"] == chk.VERIFIED}
        done -= {i for i, r in ran.items() if r["verdict"] != chk.VERIFIED}
        fpf.parent.mkdir(parents=True, exist_ok=True)
        fpf.write_text(json.dumps({"fingerprint": fp, "verified": sorted(done)}) + "\n")
    guard.close()
    budget.log_costs(costs_log, "gate", guard, err or ("run cap hit" if capped else ""))
    for r in results:
        if r["verdict"] != chk.NOT_VERIFIABLE:
            print(f'{r["id"]} {r["verdict"]}{" (not re-run)" if r.get("carried") else ""}: {r.get("readme_quote")}')
    return code


def _prev_hash(outd: Path) -> str | None:
    try:
        return json.loads((outd / "results.json").read_text()).get("readme_sha256")
    except (OSError, json.JSONDecodeError):
        return None
