# README Lie Detector

READMEs lie. Not on purpose: the code changes, the README does not, and nobody notices. README Lie Detector reads a web app's README, turns the testable sentences into claims, and checks each one in a real browser with Kane CLI. Every claim gets a verdict and screenshot evidence.

It is built for developers who write a README first and want it kept honest, and for AI coding agents that are told "the README is the spec". A false claim blocks the agent from finishing until the code makes it true.

Live report: https://velu2k03.github.io/readme-lie-detector/

## Run it

Two commands. Both take the running app URL and the README path. `rld` is `python3 -m rld`, run from the repo root.

```
python3 -m rld check --url http://127.0.0.1:4173/ --readme demo-app/README.md
python3 -m rld gate  --url http://127.0.0.1:4173/ --readme demo-app/README.md
```

- `rld check` runs every claim and writes the report to `report/`.
- `rld gate` is the cheap loop for the Stop hook. It runs previously failed claims first, stops at the first failure, and skips claims that already passed on the same README and build.

`rld gate` exits 0 when every claim is true, 1 when a claim is false or stale, 3 when the result is inconclusive, and 4 when the tool itself or Kane failed.

## Setup

1. Python 3.11 or newer and Node.js (tested with v24.22.1).
2. Create a virtual environment and install the tool's test dependency:

   ```
   python3 -m venv .venv
   . .venv/bin/activate
   pip install pytest
   ```

   The `rld` package itself uses only the Python standard library, so there is nothing else to install. 
3. Install the pinned Kane CLI: `npm install -g @testmuai/kane-cli@0.10.4`
4. Sign in with `kane-cli login --oauth`. Run `kane-cli balance` to see your credits. This project was built on a free 10,000-credit grant claimed from the Kane account billing page.
5. Install and sign in to Claude Code (`claude`). The tool uses `claude -p` once per README to extract the claims, which uses your Claude plan and no API key.
6. Check it works: `python3 -m rld --help` and `python3 -m pytest -q`.

Kane runs go through a run script. The default is the author's machine setup. On another machine set `RLD_RUN_SCRIPT` to your own script that starts Chrome and calls `kane-cli run`.

Credit safeguards are on by default: the tool refuses to start when your balance is under 2,000 credits (`RLD_MIN_CREDITS`), runs at most 12 Kane runs per invocation (`RLD_MAX_RUNS`) and 4 per claim (`RLD_MAX_CLAIM_RUNS`).

## The five verdicts

| Verdict | Meaning |
|---|---|
| VERIFIED | Kane ran the claim in a browser and it is true. |
| FALSE_CLAIM | The README says one thing, the app does another. Change the code. |
| STALE_DOC | The feature works but the README line is out of date. Change the README. |
| INCONCLUSIVE | Kane could not reach a verdict, for example a timeout. Nothing is blamed. |
| NOT_VERIFIABLE | A browser cannot check it, such as speed, privacy or install commands. |

## The report

Every run writes one static page, `report/index.html`, plus screenshots in `report/assets/`. The page opens with a verdict banner. When every claim is true it says "All 8 claims are true." Each claim has its own card showing the README line, the README quote, the value the README expected, the value Kane observed, and the screenshots from every step.

## The Stop hook

`.claude/settings.json` registers `scripts/stop-hook.sh` as a Claude Code Stop hook. When Claude Code tries to finish, the hook builds the app, runs `rld gate`, and blocks the stop if a claim is false, telling the agent which README line failed and what Kane saw. After three blocked rounds the turn is released with a warning. Set `RLD_HOOK=off` to turn the hook off.

## The demo app

`demo-app/` is Hati, a small bill splitter whose README makes eight testable claims. All eight pass. `claims.lock.json` holds the extracted claims for that README.
