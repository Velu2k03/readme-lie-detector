# Day 1 costs and unknowns (Sat 14 Nov 2026, kane-cli 0.10.4)

Target page: https://the-internet.herokuapp.com/ (has an h1 and many links; example.com has no h1 on this VM).
All runs: `kane-cli run "<objective>" --url <url> --headless --agent --timeout <s> --max-steps 25 --cdp-endpoint ...`
Chrome: Chrome for Testing 155 (puppeteer cache). Real Google Chrome was no longer installed on the VM.
Fixtures: `tests/fixtures/*.ndjson` (scrubbed copies of these three runs).

## Measured

| Run | Objective | exit | run_end.status | credits_consumed | balance drop | run_end.duration | wall clock |
|---|---|---|---|---|---|---|---|
| s5 (`pass_5step_upload_failed`) | 5 steps: assert h1, click link, assert h1, store | 0 | passed | 22.61 | 24.96 | 94.3 s | 127 s |
| s15 (`pass_15step_bifurcated`) | ~15 steps: checkbox, dropdown, add/remove, 5 assertions, store | 0 | passed | 63.86 | (see below) | 208.2 s | 243 s |
| sf (`fail_assertion`) | 1 wrong assertion ("Welcome to Hati") + store | 1 | failed | 17.55 (+2.84 verdict, inside `verdict.credits_consumed`) | (see below) | 34.3 s | 53 s |

- Balance before: 1,137.729. After s5: 1,112.771. After s15 + sf: 1,022.515.
- s15 + sf together: balance dropped 90.26, run_end credits sum 81.41. So the real balance drop runs about 10 to 15 percent above the sum of `credits_consumed`. Budget on balance drop, not on run_end.
- Total Day 1 spend: 115.2 credits for three runs.
- The 15-step objective was split by Kane into 3 flows (`bifurcated: true`, `total_runs: 3`); credits are the sum of the flows (26.4 + 15.0 + 22.5).
- Wall clock is longer than `duration` by 20 to 35 s (evidence pack, share link, upload).
- `--timeout 240` did not kill s15 at 243 s wall: the timeout seems to cover the run, not the upload tail.

## Budget math (plan section 6)

- Cost per claim: about 25 credits (5-step claim), 18 credits (single-assertion fail). 15-step claims cost about 64, so keep objectives short or the suite gets expensive.
- S, one suite of 8 claims at about 25 credits each: roughly 200 credits (balance basis about 225).
- Time per suite: 8 claims at about 2 min wall each is roughly 16 minutes. That is long for a Stop hook; use `--stop-on-red`, `--failed-first` and consider fewer claims.
- Rounds affordable = (balance - 2,000 reserve) / S.
  - With the 10,000-credit claim: (10,000 - 2,000) / 225 = about 35 rounds. Fine (needs 15+).
  - Without it (balance 1,022 now): the 2,000 reserve cannot be held. About 4 full suites in total, or roughly 40 single claims. Velu must claim the 10,000 credits for the plan to work. Until then run claims sparingly.

## The six Day 1 unknowns

1. **Credits and seconds per run.** 5-step: 22.6 credits, 94 s (127 s wall). 15-step: 63.9 credits, 208 s (243 s wall). 1-assertion fail: 17.5 credits, 34 s (53 s wall). See the table.
2. **run_end on a failed assertion.** Exit 1, `status: "failed"`, `reason: "Final verification failed: \"the page heading says 'Welcome to Hati'\""`, `reason_code: "assertion_error.final_verification"`, `result_code: 710`, `one_liner` and `summary` with Kane's explanation, plus `per_flow_metadata[]` and a `verdict` object (`confirmed`, `status: "broken"`, `family: "automation_bug"`, `category: "config_issue"`, `root_cause`, `suggestion`, `culprit_step`, `relevant_steps`, `confidence`, `credits_consumed`). `test_url` is present. **`final_state` is `{}`**: the store step never ran because the assertion stopped the run. So the Python expect-vs-final_state check can only run on a pass. Note the credits field is `credits_consumed`, not `credits` (parser reads both).
3. **Where the pack lands.** `<session_dir>/evidence/<uuid>.evidence` (`session_dir` is `~/.testmuai/kaneai/sessions/<session-id>/`). Also printed on stderr as `evidence: view locally with kane-cli evidence serve <path>`. It is a plain zip (`file` says "Zip archive data", method store), so `unzip` works. Contents: `tests/<name>/steps/<n>-<flow>-<n>/{step.json,screenshot.jpg}` plus `annotated.png` on action steps, and `v16-trajectory/*-run_summary.json` and `*-dag_diagram.md`. s15 pack: 92 files, 5 MB. rld/evidence.py can unzip and copy the screenshots. `run_dir` also exists (`.../runs/0`).
4. **test_url.** Present in s15 and sf, absent in s5. In s5 the upload step failed with `fetch failed` (see `tui.log`, `PIPELINE_FAILED`), yet the run exited **0** with status passed. So "exit 1 + passed" is not the only upload-failure shape; exit 0 + passed + no test_url also happens. The decision table already treats both the same (PASS_WARN). The test_url page (Test Manager share link) is a step-by-step replay: step list, per-step screenshot and an **Autoplay** button. There is no `<video>` element and no video file. It is a screenshot replay, not a video. For demo footage still run headed and screen-record.
5. **Clean browser profile per run?** Not when attached over `--cdp-endpoint`. After the three runs, the same Chrome still held `the-internet.herokuapp.com:rack.session` and the optimizely cookies from earlier runs. Kane does not clear state between runs on a CDP Chrome. `config show` has `chrome_profile: ""` (default) but I did not test a Kane-launched Chrome. Consequence: every Hati objective must begin with "Reset all data" (already in the plan), or rld should launch a fresh Chrome (new `--user-data-dir`) per claim.
6. **Default hook timeout.** Claude Code 2.1.319, official hooks reference (code.claude.com/docs/en/hooks): `timeout` defaults to 600 seconds for command hooks (30 s for UserPromptSubmit, 60 s for agent hooks, 30 s for prompt hooks). Set `timeout` explicitly in `.claude/settings.json`. The same page confirms `stop_hook_active` is true when Claude is already continuing because of a stop hook, and says there is an 8-consecutive-continuation cap on stop-hook loops.

## Other findings

- Exit codes seen: 0 (pass), 1 (assertion fail). Exit 2 hit once with no credits used, when Chrome was missing (`Chrome failed: fetch failed`, only `stream_start` and `recording_state` lines, no `run_end`).
- NDJSON lines seen: `stream_start`, `recording_state` (`persist:false`), `bifurcation`, step lines, `coverage`, `run_end`. `run_end` also has a large `context.memory` object (JS snippets, locators) which fixtures keep.
- Run stderr carries the `evidence:` hint and `status_disagrees advisory` notes; stdout NDJSON is clean.
- The agent's step list for the failed run shows `analyze` done then `assert` failed, so the classifier can quote the failed step remark.

## Day 2 gate run (Sun 15 Nov 2026 session, 2 claims)

`rld check` on tests/gate (heading claim true, Reset claim false): 40.2 credits by run_end, 44.8 by balance drop (1022.5 to 977.7), about 3 min wall. Verdicts: c02 VERIFIED (14.8 credits), c01 FALSE_CLAIM (25.5). Extraction and classification ran through `claude -p` (Pro plan, no API spend). Chrome reaches 127.0.0.1 directly (loopback bypasses the proxy), so local pages work.

## Run ledger (written by rld)

- 2026-11-14 13:18 gate: 3 Kane runs, 96.0 credits by run_end, balance 9747.72 -> 9644.27 (drop 103.45)
- 2026-11-14 13:34 gate: 3 Kane runs, 89.0 credits by run_end, balance 9559.83 -> 9447.69 (drop 112.13); run cap hit
- 2026-11-14 13:42 gate: 3 Kane runs, 104.0 credits by run_end, balance 9447.69 -> 9334.96 (drop 112.74); run cap hit
- 2026-11-14 13:45 gate: 1 Kane runs, 38.7 credits by run_end, balance 9334.96 -> 9284.42 (drop 50.54)
