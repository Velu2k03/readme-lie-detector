"""rld gate: the cheap loop the Stop hook runs. Same claim runner as `rld check`, plus
--failed-first (claims that were red last time go first) and --stop-on-red (stop at the first red claim, so the
agent gets one failure per round). Claims not run this round keep their previous result, marked `carried`.
Exit codes: 0 all green, 1 a FALSE_CLAIM or STALE_DOC, 3 inconclusive only, 4 infra.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

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


def gate(url: str, readme: str, out: str = "report", lock: str = "claims.lock.json", app_dir: str = "demo-app/",
         failed_first: bool = False, stop_on_red: bool = False, confirm: bool = False,
         runner=chk.run_kane, ask_json=None) -> int:
    outd = Path(out)
    outd.mkdir(parents=True, exist_ok=True)
    runs_dir = Path(".rld/runs") / time.strftime("%Y%m%d-%H%M%S")
    lk, extracted = extract.load_lock_or_extract(readme, lock, ask_json)
    prev = _previous(outd) if lk["readme_sha256"] == _prev_hash(outd) else {}
    ran: dict[str, dict] = {}
    infra, err = False, None
    for claim in order_claims(lk["claims"], prev, failed_first):
        try:
            r = chk.run_claim(claim, url, runs_dir, confirm, runner, ask_json)
        except chk.InfraError as e:
            infra, err = True, str(e)
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
    chk.finish(url, readme, lk, extracted, results, code, err, outd)
    for r in results:
        if r["verdict"] != chk.NOT_VERIFIABLE:
            print(f'{r["id"]} {r["verdict"]}{" (not re-run)" if r.get("carried") else ""}: {r.get("readme_quote")}')
    return code


def _prev_hash(outd: Path) -> str | None:
    try:
        return json.loads((outd / "results.json").read_text()).get("readme_sha256")
    except (OSError, json.JSONDecodeError):
        return None
