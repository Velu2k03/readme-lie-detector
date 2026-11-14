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
/* Design system "ledger". Light paper, one accent (burnt orange), verdict colors are semantic only.
   Type: Fraunces (display) / IBM Plex Sans (body) / IBM Plex Mono (data). Scale (px): 12 / 13 / 15 / 17 / 22 / 32 / 56-68.
   Spacing: 8px grid (--s). Radius: 2px only, hairline rules instead of boxes and shadows.
   Card: no fill, 2px ink top rule, id/verdict in a left rail, content in the right column.
   Motion: color transitions only (120ms). Nothing animates on load or scroll. Off under prefers-reduced-motion. */
:root{--paper:#f3efe6;--card:#faf8f2;--ink:#16130e;--mut:#6a6355;--rule:#d9d2c3;--accent:#c2410c;
--ok:#1f6b3a;--okb:#e0ecd9;--bad:#a4161a;--badb:#f6dcd8;--warn:#7a5200;--warnb:#f3e3b8;--mute:#4a463d;--muteb:#e4dfd2;
--s:8px;--serif:"Fraunces",Georgia,"Times New Roman",serif;--sans:"IBM Plex Sans",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:400 15px/1.6 var(--sans);-webkit-font-smoothing:antialiased}
main{max-width:1040px;margin:0 auto;padding:calc(var(--s)*6) calc(var(--s)*4) calc(var(--s)*10)}
code,pre,.cmd,.id{font-family:var(--mono);font-size:13px}
a{color:var(--ink);text-decoration-color:var(--accent);text-underline-offset:3px;text-decoration-thickness:1px}
a:hover{color:var(--accent)}
h1,h2{font-family:var(--serif);font-weight:500;font-variation-settings:"opsz" 144;letter-spacing:-.02em}
h1{font-size:clamp(36px,6vw,64px);line-height:1.02;margin:0;max-width:16ch;letter-spacing:-.03em}
h2{font-size:28px;line-height:1.15;margin:calc(var(--s)*10) 0 calc(var(--s)*3);padding-top:var(--s);border-top:2px solid var(--ink)}
h4{font:500 12px/1.4 var(--mono);text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:calc(var(--s)*2) 0 var(--s)}
.hero{display:grid;grid-template-columns:minmax(0,1fr);gap:calc(var(--s)*5);padding-bottom:calc(var(--s)*5);border-bottom:1px solid var(--rule)}
.eyebrow{display:flex;flex-wrap:wrap;gap:calc(var(--s)*1.5);align-items:center;margin:0 0 calc(var(--s)*4);font:500 12px/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--mut)}
.eyebrow::before{content:"";width:10px;height:10px;background:var(--accent)}
.badge{display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border:1px solid var(--ink);border-radius:2px;font:500 12px/1 var(--mono);letter-spacing:.02em;text-transform:none;color:var(--ink);background:transparent}
.badge.credits::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--accent)}
.stats{display:flex;flex-wrap:wrap;gap:calc(var(--s)*1) calc(var(--s)*6);margin:0;padding:0;list-style:none}
.stats li{display:flex;flex-direction:column;font-size:12px;font-family:var(--mono);text-transform:uppercase;letter-spacing:.08em;color:var(--mut)}
.stats b{font:500 56px/1 var(--serif);letter-spacing:-.03em;color:var(--ink);text-transform:none;margin-bottom:6px;font-variant-numeric:lining-nums}
.stats .bad b{color:var(--bad)}.stats .ok b{color:var(--ok)}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:calc(var(--s)*2) calc(var(--s)*4);margin:calc(var(--s)*4) 0 0;font-size:13px}
.meta span{display:flex;flex-direction:column;color:var(--mut);font:500 11px/1.4 var(--mono);text-transform:uppercase;letter-spacing:.08em;min-width:0}
.meta b{font:400 13px/1.5 var(--mono);color:var(--ink);text-transform:none;letter-spacing:0;overflow-wrap:anywhere}
.bar{display:flex;height:6px;background:var(--muteb);margin:calc(var(--s)*4) 0 var(--s)}
.bar i{display:block}.bar .ok{background:var(--ok)}.bar .bad{background:var(--bad)}.bar .warn{background:#b7791f}.bar .mute{background:#8a8472}
.legend{color:var(--mut);font:13px var(--mono);margin:0}
.changed{border-top:1px solid var(--rule);padding:0;margin:0;list-style:none}
.changed li{padding:var(--s) 0;border-bottom:1px solid var(--rule);font-size:15px}
.diagram{display:block;width:100%;height:auto}
.diagram .box{fill:var(--card);stroke:var(--ink);stroke-width:1.25}.diagram .lbl{font:500 13px var(--mono);fill:var(--ink)}
.diagram .sub{font:12px var(--mono);fill:var(--mut)}.diagram .arrow{stroke:var(--ink);stroke-width:1.25;fill:none}
.diagram .okd{fill:var(--ok)}.diagram .badd{fill:var(--bad)}.diagram .warnd{fill:#b7791f}.diagram .mutd{fill:#8a8472}
.flow{display:grid;grid-template-columns:repeat(4,1fr);gap:0;list-style:none;padding:0;margin:0;counter-reset:step;border-top:1px solid var(--rule)}
.flow li{counter-increment:step;padding:calc(var(--s)*2) calc(var(--s)*3) calc(var(--s)*2) 0;font-size:14px;color:var(--mut);line-height:1.55}
.flow li+li{padding-left:calc(var(--s)*3);border-left:1px solid var(--rule)}
.flow li::before{content:"0" counter(step);display:block;font:500 12px var(--mono);color:var(--accent);margin-bottom:var(--s)}
.flow li b{display:block;font:500 22px/1.2 var(--serif);color:var(--ink);margin-bottom:var(--s);letter-spacing:-.01em}
.card{display:grid;grid-template-columns:200px minmax(0,1fr);gap:0 calc(var(--s)*4);padding:calc(var(--s)*3) 0 calc(var(--s)*5);border-top:2px solid var(--ink);margin:0}
.card+.card{margin-top:calc(var(--s)*2)}
.card>*{grid-column:2;min-width:0}
.card>header{grid-column:1;grid-row:1/span 12;display:flex;flex-direction:column;align-items:flex-start;gap:var(--s);position:sticky;top:calc(var(--s)*3);align-self:start}
.id{color:var(--ink);font-size:32px;font-family:var(--serif);font-weight:500;letter-spacing:-.02em;order:-1}
.chip{display:inline-flex;gap:6px;align-items:center;padding:4px 8px;border-radius:2px;font:500 12px/1.2 var(--mono);text-transform:uppercase;letter-spacing:.06em}
.chip.ok{background:var(--okb);color:var(--ok)}.chip.bad{background:var(--badb);color:var(--bad)}
.chip.warn{background:var(--warnb);color:var(--warn)}.chip.mute{background:var(--muteb);color:var(--mute)}
blockquote{margin:0 0 calc(var(--s)*2);padding:calc(var(--s)*2);background:var(--card);border:1px solid var(--rule);border-radius:2px;display:flex;gap:calc(var(--s)*2)}
blockquote .ln{flex:none;color:var(--mut);font:12px var(--mono)}blockquote code{word-break:break-word;font-size:13px;line-height:1.55}
.one{font:500 17px/1.45 var(--sans);margin:0 0 var(--s)}.muted{color:var(--mut);font-size:13px;margin:var(--s) 0}.hint{font-size:14px;margin:var(--s) 0}
.ev{display:grid;grid-template-columns:1fr 1fr;gap:0;margin:calc(var(--s)*2) 0;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}
.ev section{padding:0 calc(var(--s)*2) var(--s) 0;min-width:0}.ev section+section{padding-left:calc(var(--s)*2);border-left:1px solid var(--rule)}
.kv{display:flex;flex-direction:column;margin-bottom:var(--s)}.kv .k{font:11px var(--mono);color:var(--mut);text-transform:uppercase;letter-spacing:.06em}.kv code{word-break:break-word}
.proof{margin:calc(var(--s)*2) 0}.proof .main{width:100%;max-height:480px;object-fit:contain;object-position:top left;border:1px solid var(--rule);border-radius:2px;display:block;cursor:zoom-in;background:#fff}
.proof figcaption{color:var(--mut);font-size:12px;margin:var(--s) 0}
.film{display:flex;gap:var(--s);overflow-x:auto;padding-bottom:var(--s)}
.thumb{height:56px;border:1px solid var(--rule);border-radius:2px;cursor:pointer;flex:none;background:#fff;opacity:.7;transition:opacity .12s}.thumb:hover{opacity:1}.thumb.on{border-color:var(--ink);outline:1px solid var(--ink);opacity:1}
.attempts{color:var(--mut);font:12px var(--mono);margin:var(--s) 0}
details{margin:var(--s) 0;font-size:14px}summary{cursor:pointer;color:var(--ink);font:500 12px var(--mono);text-transform:uppercase;letter-spacing:.08em}
pre{white-space:pre-wrap;word-break:break-word;background:var(--card);border:1px solid var(--rule);padding:calc(var(--s)*1.5);border-radius:2px;margin:0}
ul{padding-left:calc(var(--s)*3);margin:0}li{font-size:13px}
.links{display:flex;flex-wrap:wrap;gap:calc(var(--s)*2);align-items:center;margin-top:calc(var(--s)*2)}
.btn{display:inline-block;padding:var(--s) calc(var(--s)*2);border:1px solid var(--ink);border-radius:2px;color:var(--ink);text-decoration:none;font:500 13px var(--mono);transition:background .12s,color .12s}
.btn:hover{background:var(--ink);color:var(--paper)}.cmd{color:var(--mut);overflow-wrap:anywhere}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:calc(var(--s)*1.5) calc(var(--s)*2) calc(var(--s)*1.5) 0;border-bottom:1px solid var(--rule);vertical-align:top}
th{color:var(--mut);font:500 11px var(--mono);text-transform:uppercase;letter-spacing:.08em;border-bottom:1px solid var(--ink)}
footer{margin-top:calc(var(--s)*10);color:var(--mut);font-size:13px;border-top:2px solid var(--ink);padding-top:calc(var(--s)*3);display:grid;grid-template-columns:repeat(3,1fr);gap:calc(var(--s)*2) calc(var(--s)*4)}
footer p{margin:0}footer .wide{grid-column:1/-1}
.foot-badges{display:flex;flex-wrap:wrap;gap:var(--s)}
#lb{position:fixed;inset:0;background:rgba(22,19,14,.88);display:none;align-items:center;justify-content:center;cursor:zoom-out;z-index:9}
#lb.on{display:flex}#lb img{max-width:94vw;max-height:94vh;background:#fff}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media(max-width:860px){.card{grid-template-columns:1fr}.card>*,.card>header{grid-column:1}.card>header{grid-row:auto;position:static;flex-direction:row;align-items:center;justify-content:space-between;margin-bottom:var(--s)}.id{order:0}
.flow{grid-template-columns:1fr 1fr}.flow li:nth-child(3){padding-left:0;border-left:0}.flow li:nth-child(n+3){border-top:1px solid var(--rule)}footer{grid-template-columns:1fr}}
@media(max-width:640px){main{padding:calc(var(--s)*4) calc(var(--s)*2) calc(var(--s)*8)}.ev{grid-template-columns:1fr}.ev section+section{padding-left:0;border-left:0;border-top:1px solid var(--rule);padding-top:var(--s)}
.flow{grid-template-columns:1fr}.flow li,.flow li+li{padding-left:0;border-left:0}.flow li+li{border-top:1px solid var(--rule)}.stats b{font-size:44px}.diagram{display:none}h2{font-size:24px}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
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


DIAGRAM = """<svg class="diagram" viewBox="0 0 840 150" role="img" aria-label="README to claims to real browser run to verdicts">
<rect class="box" x="4" y="35" width="150" height="80" rx="10"/><text class="lbl" x="79" y="70" text-anchor="middle">README</text><text class="sub" x="79" y="92" text-anchor="middle">the spec</text>
<path class="arrow" d="M158 75H238"/><rect class="box" x="242" y="35" width="150" height="80" rx="10"/><text class="lbl" x="317" y="70" text-anchor="middle">Claims</text><text class="sub" x="317" y="92" text-anchor="middle">testable sentences</text>
<path class="arrow" d="M396 75H476"/><rect class="box" x="480" y="35" width="150" height="80" rx="10"/><text class="lbl" x="555" y="70" text-anchor="middle">Kane + Chrome</text><text class="sub" x="555" y="92" text-anchor="middle">real browser run</text>
<path class="arrow" d="M634 75H694"/><rect class="box" x="698" y="12" width="138" height="126" rx="10"/><text class="lbl" x="767" y="36" text-anchor="middle">Verdicts</text>
<circle class="okd" cx="716" cy="58" r="5"/><text class="sub" x="728" y="62">verified</text><circle class="badd" cx="716" cy="80" r="5"/><text class="sub" x="728" y="84">false claim</text>
<circle class="warnd" cx="716" cy="102" r="5"/><text class="sub" x="728" y="106">stale doc</text><circle class="mutd" cx="716" cy="124" r="5"/><text class="sub" x="728" y="128">inconclusive</text></svg>"""

FLOW = """<h2>How it works</h2><ol class="flow">
<li><b>Read</b>Picks the sentences in the README that a browser can check and copies each expected value from the text.</li>
<li><b>Run</b>Kane CLI performs each claim in a real Chrome and saves a screenshot at every step.</li>
<li><b>Compare</b>A second check compares the value Kane read with the README value.</li>
<li><b>Classify</b>A failure is a false claim (fix the code), a stale doc (fix the README) or a bad test (rewritten, never softened).</li></ol>"""


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
    stats = "".join(f'<li class="{c}"><b>{counts[c]}</b>{w}</li>' for c, w in
                    (("ok", "verified"), ("bad", "false claim"), ("warn", "stale doc"), ("mute", "inconclusive")) if counts[c] or c == "ok")
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
<title>README Lie Detector report</title><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500&display=swap"><style>{CSS}</style></head><body><main>
<section class="hero"><div><p class="eyebrow">README Lie Detector <span class="badge credits">{doc.get("total_credits", 0):.1f} Kane credits this run</span></p>
<h1>{E(head)}</h1></div><ul class="stats">{stats}</ul>{DIAGRAM}</section>
<p class="meta">{metaf}</p>
<div class="bar" role="img" aria-label="{E(legend)}">{bar}</div><p class="legend">{E(legend)}</p>{infra}
{changed}
{FLOW}
<h2>Claims</h2>
{"".join(_card(r, doc, sha) for r in cards) or '<p class="muted">No testable claims.</p>'}
{nvt}
<footer><p>How it works: it reads your README and picks the claims a browser can check, copying every expected value from the README text.</p>
<p>Kane CLI runs each claim in a real Chrome and returns a pass or fail with screenshots; a second check compares the value it read with the README.</p>
<p>A failure is classified as a false claim (fix the code), a stale doc (fix the README) or a bad test (rewritten, never softened).</p>
<p class="wide">Reproduce this report: <code>{E(cmd)}</code></p>
<div class="foot-badges wide"><span class="badge">Verdicts come from real browser runs</span><span class="badge credits">{doc.get("total_credits", 0):.1f} credits</span><span class="badge">Built with Claude Code and Kane CLI</span></div>
<p class="wide">README Lie Detector &middot; <a href="https://github.com/Velu2k03/readme-lie-detector" target="_blank" rel="noopener">source on GitHub</a></p></footer></main>
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
