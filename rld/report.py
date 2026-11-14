"""Render report/index.html from results.json: one static file, CSS + JS + data inline.

Screenshots live in report/assets/<claim-id>/ and are referenced by relative path.
Each render also saves a snapshot to report/history/<time>.json; the newest earlier snapshot drives the
"Changed since last run" section. Standard library only.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import time
from pathlib import Path

from . import evidence

ORDER = {"FALSE_CLAIM": 0, "STALE_DOC": 1, "INCONCLUSIVE": 2, "VERIFIED": 3}
CHIP = {"VERIFIED": ("Verified", "ok", "✓"), "FALSE_CLAIM": ("False claim", "bad", "✕"),
        "STALE_DOC": ("Stale doc", "warn", "!"), "INCONCLUSIVE": ("Inconclusive", "mute", "?")}
E = html.escape


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def github_line_url(readme: str, line, sha: str) -> str | None:
    """https://github.com/<o>/<r>/blob/<sha>/<path>#L<line>, or None when there is no GitHub remote."""
    remote = _git("config", "--get", "remote.origin.url")
    m = re.match(r"^(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?/?$", remote)
    top = _git("rev-parse", "--show-toplevel")
    if not (m and top and sha and line):
        return None
    try:
        rel = Path(readme).resolve().relative_to(Path(top).resolve()).as_posix()
    except ValueError:
        return None
    return f"https://github.com/{m[1]}/blob/{sha}/{rel}#L{line}"


def _fmt_dur(s) -> str:
    s = int(round(s or 0))
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def _home(p: str | None) -> str:
    return (p or "").replace(os.path.expanduser("~"), "~")


def attempts_line(r: dict) -> str:
    parts, confirmed = [], False
    for a in r.get("attempts", []):
        note = a.get("note") or ""
        if "rewritten" in note:
            what = "bad test, rewritten"
        elif a.get("decision") in ("PASS", "PASS_WARN"):
            what = "passed"
        elif "confirm re-run" in note:
            what, confirmed = "failed, re-run to confirm", True
        elif a.get("decision") == "ASSERT_FAIL":
            what = "failed"
        else:
            what = str(a.get("decision", "")).lower() or "ran"
        parts.append(f"attempt {a.get('attempt')} {what}")
    if confirmed and r.get("verdict") in ("FALSE_CLAIM", "STALE_DOC"):
        parts.append("confirmed on re-run")
    return "; ".join(parts) or "no attempts recorded"


def headline(results: list[dict]) -> tuple[str, str]:
    testable = [r for r in results if r["verdict"] != "NOT_VERIFIABLE"]
    n = len(testable)
    ok = sum(r["verdict"] == "VERIFIED" for r in testable)
    wrong = sum(r["verdict"] in ("FALSE_CLAIM", "STALE_DOC") for r in testable)
    unk = sum(r["verdict"] == "INCONCLUSIVE" for r in testable)
    if not n:
        return "No testable claims found.", ""
    if ok == n:
        return f"All {n} claims are true. This README told the truth.", ""
    s = f"{ok} of {n} claims are true."
    if wrong:
        s += f" This README is wrong in {wrong} place{'s' if wrong != 1 else ''}."
    if unk:
        s += f" {unk} could not be checked."
    return s, ""


def changed_since(prev: dict | None, results: list[dict]) -> list[str]:
    if not prev:
        return []
    key = lambda r: r.get("readme_quote") or r["id"]  # noqa: E731
    old = {key(r): r for r in prev.get("results", []) if r["verdict"] != "NOT_VERIFIABLE"}
    new = {key(r): r for r in results if r["verdict"] != "NOT_VERIFIABLE"}
    out = []
    for k, r in new.items():
        o = old.get(k)
        if o is None:
            out.append(f"{r['id']} new claim, {r['verdict']}")
        elif o["verdict"] != r["verdict"]:
            out.append(f"{r['id']} {o['verdict']} to {r['verdict']}")
    for k, o in old.items():
        if k not in new:
            out.append(f"{o['id']} removed from README: “{k[:90]}”")
    return out


def _kv(d: dict | None, empty: str) -> str:
    if not d:
        return f'<p class="muted">{E(empty)}</p>'
    return "".join(f'<div class="kv"><span class="k">{E(str(k))}</span><code>{E(str(v))}</code></div>'
                   for k, v in d.items())


def _card(r: dict, doc: dict, sha: str) -> str:
    label, cls, glyph = CHIP.get(r["verdict"], (r["verdict"], "mute", "?"))
    line = r.get("readme_line")
    url = github_line_url(doc.get("readme", ""), line, sha)
    ln = (f'<a href="{E(url)}" target="_blank" rel="noopener">line {line}</a>' if url else f"line {line}")
    frames = r.get("frames") or []
    fid = E(r["id"])
    if frames:
        big = f'assets/{fid}/{E(frames[-1]["file"])}'
        thumbs = "".join(
            f'<img class="thumb{" on" if i == len(frames) - 1 else ""}" loading="lazy" src="assets/{fid}/{E(f["file"])}" '
            f'alt="step {f["step"]}" data-full="assets/{fid}/{E(f["file"])}">' for i, f in enumerate(frames))
        proof = (f'<figure class="proof"><img class="main zoom" src="{big}" alt="Last screenshot for {fid}">'
                 f'<figcaption>Last frame (step {frames[-1]["step"]}). Click to enlarge; pick an earlier step below.</figcaption>'
                 f'<div class="film">{thumbs}</div></figure>')
    else:
        proof = ('<p class="muted">No screenshots were available for this run. The step remarks (under Details) and the '
                 'Kane Test Manager link show what happened.</p>')
    carried = ('<p class="muted">Not re-run this round (stop-on-red). Result is from an earlier run.</p>'
               if r.get("carried") else "")
    remarks = "".join(f"<li>{E(x)}</li>" for x in r.get("step_remarks", [])) or "<li>none</li>"
    links = []
    if r.get("test_url"):
        links.append(f'<a class="btn" href="{E(r["test_url"])}" target="_blank" rel="noopener">Open run in Kane Test Manager</a>')
    if r.get("evidence_pack"):
        links.append(f'<span class="cmd">Full pack: <code>kane-cli evidence serve {E(_home(r["evidence_pack"]))}</code></span>')
    elif r.get("session_dir"):
        links.append('<span class="cmd">Full pack: <code>kane-cli evidence serve &lt;pack&gt;</code> (pack not found on this machine)</span>')
    hint = f'<p class="hint"><b>Fix rule:</b> {E(r["fix_hint"])}</p>' if r.get("fix_hint") else ""
    why = f'<p class="muted">{E(r["reason"])}</p>' if r.get("reason") and r["verdict"] != "VERIFIED" else ""
    exp = _kv(r.get("expect"), "No expected value recorded.")
    obs = _kv(r.get("observed"), "Nothing stored: the run stopped before the store step."
              if r["verdict"] != "VERIFIED" else "Nothing stored.")
    return f"""<article class="card {cls}" id="{fid}">
<header><span class="chip {cls}"><span aria-hidden="true">{glyph}</span> {label}</span><span class="id">{fid}</span></header>
<blockquote><span class="ln">{ln}</span><code>{E(r.get("readme_quote") or "")}</code></blockquote>
<p class="one">{E(r.get("one_liner") or "")}</p>{why}{hint}{carried}
<div class="ev"><section><h4>Expected (README)</h4>{exp}</section><section><h4>Observed (Kane)</h4>{obs}</section></div>
{proof}
<p class="attempts">{E(attempts_line(r))}</p>
<details><summary>Details</summary>
<h4>Objective</h4><pre>{E(r.get("objective") or "")}</pre>
<h4>Summary</h4><p>{E(r.get("summary") or "none")}</p>
<h4>Step remarks</h4><ul>{remarks}</ul>
<p class="muted">Duration {_fmt_dur(r.get("duration"))} &middot; credits {r.get("credits", 0):.1f}</p></details>
<div class="links">{"".join(links)}</div>
</article>"""


CSS = """
:root{--bg:#fafafa;--fg:#111;--mut:#6b6b6b;--bd:#e4e4e7;--card:#fff;--ok:#15803d;--okb:#dcfce7;--bad:#b91c1c;--badb:#fee2e2;
--warn:#92400e;--warnb:#fef3c7;--mute:#3f3f46;--muteb:#e4e4e7;--s:8px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
main{max-width:880px;margin:0 auto;padding:calc(var(--s)*5) calc(var(--s)*3) calc(var(--s)*8)}
code,pre,.cmd{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px}
.meta{display:flex;flex-wrap:wrap;gap:var(--s) calc(var(--s)*3);color:var(--mut);font-size:13px;margin:0 0 calc(var(--s)*4)}
.meta b{color:var(--fg);font-weight:500}
h1{font-size:34px;line-height:1.15;letter-spacing:-.02em;margin:0 0 calc(var(--s)*2);font-weight:650}
h2{font-size:18px;margin:calc(var(--s)*6) 0 calc(var(--s)*2);font-weight:600}
h4{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin:calc(var(--s)*2) 0 var(--s);font-weight:600}
.bar{display:flex;height:8px;border-radius:4px;overflow:hidden;background:var(--muteb);margin-bottom:var(--s)}
.bar i{display:block}.bar .ok{background:var(--ok)}.bar .bad{background:var(--bad)}.bar .warn{background:#d97706}.bar .mute{background:#a1a1aa}
.legend{color:var(--mut);font-size:13px;margin:0}
.changed{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:calc(var(--s)*2);margin:0;list-style:none}
.changed li{padding:calc(var(--s)/2) 0}
.card{background:var(--card);border:1px solid var(--bd);border-left-width:4px;border-radius:8px;padding:calc(var(--s)*3);margin:0 0 calc(var(--s)*3)}
.card.bad{border-left-color:var(--bad)}.card.ok{border-left-color:var(--ok)}.card.warn{border-left-color:#d97706}.card.mute{border-left-color:#a1a1aa}
.card header{display:flex;justify-content:space-between;align-items:center;margin-bottom:calc(var(--s)*2)}
.id{color:var(--mut);font-family:ui-monospace,monospace;font-size:13px}
.chip{display:inline-flex;gap:var(--s);align-items:center;padding:calc(var(--s)/2) calc(var(--s)*1.5);border-radius:999px;font-size:13px;font-weight:600}
.chip.ok{background:var(--okb);color:var(--ok)}.chip.bad{background:var(--badb);color:var(--bad)}
.chip.warn{background:var(--warnb);color:var(--warn)}.chip.mute{background:var(--muteb);color:var(--mute)}
blockquote{margin:0 0 calc(var(--s)*2);padding:calc(var(--s)*1.5) calc(var(--s)*2);background:#f4f4f5;border-radius:6px;display:flex;gap:calc(var(--s)*2)}
blockquote .ln{flex:none;color:var(--mut);font-size:13px}blockquote code{word-break:break-word}
.one{font-weight:500;margin:0 0 var(--s)}.muted{color:var(--mut);font-size:13px;margin:var(--s) 0}.hint{font-size:13px;margin:var(--s) 0}
.ev{display:grid;grid-template-columns:1fr 1fr;gap:calc(var(--s)*2);margin:calc(var(--s)*2) 0}
.ev section{border:1px solid var(--bd);border-radius:6px;padding:0 calc(var(--s)*2) var(--s)}
.kv{display:flex;flex-direction:column;margin-bottom:var(--s)}.kv .k{font-size:12px;color:var(--mut)}.kv code{word-break:break-word}
.proof{margin:calc(var(--s)*2) 0}.proof .main{width:100%;max-height:480px;object-fit:contain;object-position:top left;border:1px solid var(--bd);border-radius:6px;display:block;cursor:zoom-in;background:#fff}
.proof figcaption{color:var(--mut);font-size:12px;margin:var(--s) 0}
.film{display:flex;gap:var(--s);overflow-x:auto;padding-bottom:var(--s)}
.thumb{height:56px;border:2px solid var(--bd);border-radius:4px;cursor:pointer;flex:none;background:#fff}.thumb.on{border-color:var(--fg)}
.attempts{color:var(--mut);font-size:13px;margin:var(--s) 0}
details{margin:var(--s) 0;font-size:14px}summary{cursor:pointer;color:var(--mut)}
pre{white-space:pre-wrap;word-break:break-word;background:#f4f4f5;padding:calc(var(--s)*1.5);border-radius:6px;margin:0}
ul{padding-left:calc(var(--s)*3);margin:0}li{font-size:13px}
.links{display:flex;flex-wrap:wrap;gap:calc(var(--s)*2);align-items:center;margin-top:calc(var(--s)*2)}
.btn{display:inline-block;padding:var(--s) calc(var(--s)*2);border:1px solid var(--fg);border-radius:6px;color:var(--fg);text-decoration:none;font-size:13px;font-weight:500}
a{color:inherit}.cmd{color:var(--mut)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--bd);border-radius:8px;font-size:13px}
th,td{text-align:left;padding:calc(var(--s)*1.5) calc(var(--s)*2);border-bottom:1px solid var(--bd);vertical-align:top}th{color:var(--mut);font-weight:600}
footer{margin-top:calc(var(--s)*8);color:var(--mut);font-size:13px;border-top:1px solid var(--bd);padding-top:calc(var(--s)*3)}
footer p{margin:0 0 var(--s)}
#lb{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-content:center;cursor:zoom-out;z-index:9}
#lb.on{display:flex}#lb img{max-width:94vw;max-height:94vh;background:#fff}
@media(max-width:640px){.ev{grid-template-columns:1fr}h1{font-size:26px}}
"""

JS = """
(function(){var lb=document.getElementById('lb'),li=lb.querySelector('img');
document.addEventListener('click',function(e){var t=e.target;
if(t.classList.contains('thumb')){var f=t.closest('.proof'),m=f.querySelector('.main');m.src=t.dataset.full;
f.querySelectorAll('.thumb').forEach(function(x){x.classList.remove('on')});t.classList.add('on');}
else if(t.classList.contains('zoom')){li.src=t.src;lb.classList.add('on');}
else if(lb.contains(t)){lb.classList.remove('on');}});
document.addEventListener('keydown',function(e){if(e.key==='Escape')lb.classList.remove('on');});})();
"""


def render_html(doc: dict, prev: dict | None, sha: str) -> str:
    results = doc.get("results", [])
    cards = sorted([r for r in results if r["verdict"] != "NOT_VERIFIABLE"],
                   key=lambda r: (ORDER.get(r["verdict"], 9), r["id"]))
    nv = [r for r in results if r["verdict"] == "NOT_VERIFIABLE"]
    head, _ = headline(results)
    counts = {c: sum(r["verdict"] == v for r in cards) for v, c in
              (("VERIFIED", "ok"), ("FALSE_CLAIM", "bad"), ("STALE_DOC", "warn"), ("INCONCLUSIVE", "mute"))}
    total = max(len(cards), 1)
    bar = "".join(f'<i class="{c}" style="width:{n * 100 / total:.1f}%"></i>' for c, n in counts.items() if n)
    legend = " · ".join(f"{n} {w}" for n, w in (
        (counts["ok"], "verified"), (counts["bad"], "false"), (counts["warn"], "stale doc"), (counts["mute"], "inconclusive")) if n)
    chg = changed_since(prev, results)
    changed = ('<h2>Changed since last run</h2><ul class="changed">' + "".join(f"<li>{E(x)}</li>" for x in chg) + "</ul>"
               if prev and chg else ('<h2>Changed since last run</h2><ul class="changed"><li>No changes.</li></ul>' if prev else ""))
    dur = sum((r.get("duration") or 0) for r in results if not r.get("carried"))
    meta = [("App", doc.get("url")), ("README", doc.get("readme")), ("Commit", sha or "n/a"),
            ("Run", doc.get("run_at", "")), ("Kane CLI", doc.get("cli_version") or "n/a"),
            ("Duration", _fmt_dur(dur)), ("Credits", f'{doc.get("total_credits", 0):.1f}')]
    metaf = "".join(f"<span>{k} <b>{E(str(v))}</b></span>" for k, v in meta)
    nvt = ("<h2>Not verifiable</h2><table><tr><th>README quote</th><th>Line</th><th>Reason</th></tr>" +
           "".join(f"<tr><td><code>{E(r.get('readme_quote') or '')}</code></td><td>{r.get('readme_line')}</td>"
                   f"<td>{E(r.get('reason') or '')}</td></tr>" for r in nv) + "</table>") if nv else ""
    infra = (f'<p class="hint"><b>Infra error:</b> {E(doc["infra_error"])}. The suite stopped early.</p>'
             if doc.get("infra_error") else "")
    data = json.dumps(doc).replace("<", "\\u003c")
    cmd = f'python3 -m rld check --url {doc.get("url")} --readme {doc.get("readme")}'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>README Lie Detector report</title><style>{CSS}</style></head><body><main>
<p class="meta">{metaf}</p>
<h1>{E(head)}</h1><div class="bar" role="img" aria-label="{E(legend)}">{bar}</div><p class="legend">{E(legend)}</p>{infra}
{changed}
<h2>Claims</h2>
{"".join(_card(r, doc, sha) for r in cards) or '<p class="muted">No testable claims.</p>'}
{nvt}
<footer><p>How it works: it reads your README and picks the claims a browser can check, copying every expected value from the README text.</p>
<p>Kane CLI runs each claim in a real Chrome and returns a pass or fail with screenshots; a second check compares the value it read with the README.</p>
<p>A failure is classified as a false claim (fix the code), a stale doc (fix the README) or a bad test (rewritten, never softened).</p>
<p>Reproduce this report: <code>{E(cmd)}</code></p></footer></main>
<div id="lb"><img alt="enlarged screenshot"></div>
<script id="rld-data" type="application/json">{data}</script><script>{JS}</script></body></html>"""


def build(doc: dict, out: str | Path) -> Path:
    """Collect screenshots, snapshot history, write report/index.html. Returns the index path."""
    outd = Path(out)
    hist = outd / "history"
    hist.mkdir(parents=True, exist_ok=True)
    prev = None
    snaps = sorted(hist.glob("*.json"))
    if snaps:
        try:
            prev = json.loads(snaps[-1].read_text())
        except json.JSONDecodeError:
            prev = None
    for r in doc.get("results", []):
        if r["verdict"] == "NOT_VERIFIABLE" or r.get("frames") is not None:
            continue
        ev = evidence.collect(r.get("session_dir"), r.get("run_dir"), outd / "assets" / r["id"])
        r["frames"], r["evidence_pack"] = ev["frames"], ev["pack"]
    doc.setdefault("run_at", time.strftime("%Y-%m-%d %H:%M:%S %Z"))
    sha = doc.get("commit") or _git("rev-parse", "HEAD")
    doc["commit"] = sha[:7]
    index = outd / "index.html"
    index.write_text(render_html(doc, prev, sha), encoding="utf-8")
    (hist / (time.strftime("%Y%m%d-%H%M%S") + ".json")).write_text(json.dumps(doc, indent=2) + "\n")
    return index
