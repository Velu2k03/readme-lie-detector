# Credit safeguards: where Kane credits can leak, and the fixes

Audit of 14 Nov 2026 (Day 4), written for Velu. All numbers come from `.rld/runs/*` (the real run logs), `docs/COSTS.md` and the code at commit 3f4be2f. No Kane run was made for this work. The only Kane command used was the free, read-only `kane-cli balance`, which printed 9999.9634, so the 10,000 claim has landed.

## 1. Where the ~857 credits of Day 4 went (the proof)

I summed `credits_consumed` from every run on disk: **847 credits across 15 gate runs** (balance says ~857, so the logs are complete).

| What happened | Evidence | Credits |
|---|---|---|
| Multi-claim gates re-run again and again | dirs `113242` (9 runs), `113252` (4), `114257` (3), `110649`/`111524` (3 each) | ~640 |
| **Two gates running at the same time**, nothing stopped it | `113242` and `113252` started 10 s apart, 238.7 + 82.8 credits | ~320 of the above |
| "Insufficient credits" loop, 3 times in a row | `115305`, `115742`, `120207`: 8 runs each, every one `infra_error.credits_exhausted` | **0 credits, but 24 Kane+Chrome launches and ~10 min** |

Two plan claims the code does not back up:
- Plan: "`--stop-on-red` ... green claims are not re-run". **False.** The code only stops at a red claim. When the red one turns green, the loop carries on through all the others, so a green gate is a full suite (200-225 credits) every time.
- Plan: "the fingerprint skip" is listed as a credit control. **It was never written** (`git grep -i fingerprint` finds only a docstring).

## 2. Every loop that can spend credits

| # | Place | Bounded? | Worst case before | Fix now |
|---|---|---|---|---|
| 1 | `run_claim` loop | Yes, but wide: 4 passes (first + 2 rewrites + confirm), each can add a timeout retry | **8 Kane runs for ONE claim, ~200 credits** (a whole suite) | per-claim cap 4 (~100) |
| 2 | `check()` runs all claims | Never skips green | 8 claims x 8 = 64 runs on paper, ~225 real | run cap 12 per invocation |
| 3 | `gate()` | `--failed-first` was ON only via the shell script; bare `rld gate` had both OFF. Stop-on-red does not stop green runs (see above) | full suite per gate | defaults ON, fingerprint skip, cap |
| 4 | Stop hook, MAX_BLOCKS=3 | Counter is per session file but **resets to 0 on every new Stop request** (`stop_hook_active` false), so the cap is per turn, not per session | 4 gate runs per turn (3 blocks + the release run) | gate skip makes unchanged turns free; red-unchanged is residual (see 5) |
| 5 | Hook fires on a chat-only turn | Yes it runs build + gate on every Stop, even if nothing changed | one full suite per turn | fingerprint skip |
| 6 | `serve-and-check.sh` | Rebuilds on every Stop. No credits, a few seconds | 0 credits | left alone (build output is what the fingerprint hashes) |
| 7 | Classifier rewrite loop | `MAX_REWRITES=2` **is enforced** (`rewrites >= MAX_REWRITES`); "unproven" never loops | 3 runs (+ retries) | inside the per-claim cap now |
| 8 | "Insufficient credits" | Not a loop on credits (0 consumed) but `decide()` says "INCONCLUSIVE, continue with other claims", so all 8 claims launched | 0 credits, ~25 s each | stops at once on `credits_exhausted`; 3 infra results in a row abort; balance pre-flight |
| 9 | `run_kane` hang | `subprocess.run(timeout=)` kills only `bash`, so `kane-cli` and Chrome could keep running and keep spending | unbounded | whole process group is killed; no exit file = exit 2 = abort |
| 10 | Extract step | Only calls `claude -p` when the README hash changes (`load_lock_or_extract`). Classify and rewrite also call it. Claude Pro usage, not Kane | 0 credits | none needed |
| 11 | Nested `claude -p` firing the Stop hook | Currently safe (it runs from a temp dir, and `~/.claude/settings.json` has no hooks) but one config change would make gate call claude call gate | unbounded | `RLD_HOOK=off` is passed to every nested call |
| 12 | Two gates at once | Nothing stopped it (see table above) | ~320 on Day 4 | `.rld/run.lock`, second run exits 4 |

## 3. Safeguards, ranked by credits saved, with both sides argued

**A. Fingerprint skip (saves the most, ~600+/day at the Day 4 rate).** A claim that was VERIFIED on the same README + build (sha256 over README hash and `demo-app/dist`) is not re-run; if all are, the gate prints "no changes, gate skipped" and spends nothing. A capped gate resumes with only the unverified claims.
- For: dirs `110649` to `114257` are 3 to 9 runs each, and nothing skipped claims already verified on the same build.
- Against: a flaky green is trusted until the build changes. A build that is not byte-identical for identical source (timestamps) would never skip. Cheaper alternative: none that is safe.
- Trade-off: `RLD_FORCE=1` re-runs everything. If the README changes, every claim re-runs (ids can be re-mapped by re-extraction, so carrying them would be wrong).

**B. Credits-exhausted stop + 3-in-a-row infra breaker.** Saves 0 credits (the runs were free) but 10 minutes and the agent's patience per Stop; protects the case where a run is billed but returns no result.
- Against: three timeouts in a row also trip it. That is fine, three runs with no result in a row means something is broken.

**C. Run lock.** The only fix aimed at the 321-credit double run. Against: none that matters; a crashed run frees the lock because `flock` is released on exit.

**D. Per-claim cap 4.** Halves the worst case for one claim (200 to 100).
- Against: it can cut a legitimate rescue (timeout, rewrite, rewrite, confirm). Cost of that: one INCONCLUSIVE instead of a verdict. Override with `RLD_MAX_CLAIM_RUNS`.

**E. Balance pre-flight, reserve 2,000.** Checked before the first run and before every run (one free `kane-cli balance` call each), so it overshoots by at most one claim. If the balance cannot be read it **fails closed** (exit 4) unless `RLD_MIN_CREDITS=0`.
- Against: on demo day it blocks you at 2,000 until you set `RLD_MIN_CREDITS=0` (or 200). That is on purpose, but remember it.

**F. Per-invocation cap 12.** Stops a runaway but a full all-green pass of 8 claims plus 4 retries fits inside 12, so it does **not** stop a normal full suite. See "what is still open".

**G. Gate defaults (`--failed-first`, `--stop-on-red` on; `--no-...` to turn off).** Saves little by itself, see the plan pushback above. Cheap and correct, keep.

**H. Kill the whole run on a hang, `RLD_HOOK=off` for nested claude, cost ledger.** Insurance and visibility. The ledger appends date, runs, credits by `run_end`, and balance before/after to this folder's `COSTS.md`. Judge spend by the balance drop: `COSTS.md` measured it 10-15% above `run_end`, and a timed-out run records 0 credits.

**Rejected, not worth it:**
- Caching a red result and replaying it when nothing changed: it would freeze a flaky red (the plan itself says "red once, green on a re-run"), and the hook ignores carried results anyway.
- Skipping the rebuild in `serve-and-check.sh`: saves seconds, no credits, and touches `scripts/`.
- A daily credit budget: the reserve plus the ledger already covers it.

## 4. The reserve: 2,000 is right, slightly generous

- Spendable now: 9,999.96 - 2,000 = ~8,000 = 35 full suites at 225.
- Day 4 burned 857 *with* the loops. Even 5 more days at that rate is ~4,300, well under 8,000. The reserve will not bind before demo day.
- Demo day need: 2 rehearsal suites (450) + 1 recorded suite (225) + confirm re-runs (~50) + 2 retakes (450) = ~1,200. So 2,000 is ~1.6 times the need.
- Verdict: keep 2,000. It costs nothing while the balance is high and it is the brake if a loop gets through. If it ever blocks real work, lower to 1,200, not below. On Nov 19 set `RLD_MIN_CREDITS=0` on purpose. Credits are valid one month, so unspent credits at the end are wasted, which is why the reserve should not be raised.

## 5. What is still open (you decide)

1. **Rule 1 (never a full suite without your OK) is not fully enforced by code.** After any build change, an all-green gate still runs up to 12 claims (~225). I did not change `scripts/` or `.claude/`. Suggested: start Claude Code with `RLD_MAX_RUNS=3` while iterating (the hook then runs the red claim plus 2 others and exits 3, which does not block) and run `rld check` yourself, with your go-ahead, for the full suite.
2. **Red claim, nothing changed:** the hook re-runs the red claim up to 4 times per turn, ~25 credits each, ~100 per turn. Set `RLD_HOOK=off` when you are not working on the code.
3. **`kane-cli testmd` replays** are said to cost zero credits (plan, event FAQ). Fable never verified the format. If true it is the biggest saver of all; worth one read of the docs on Day 5.
4. Concurrency and the cap only protect this checkout. A second clone or a manual `kane-cli run` is outside the guard.

## 6. Settings

| Env var | Default | Meaning |
|---|---|---|
| `RLD_MIN_CREDITS` | 2000 | refuse to run Kane below this balance; 0 turns the check off |
| `RLD_MAX_RUNS` | 12 | Kane runs per `rld check` / `rld gate` |
| `RLD_MAX_CLAIM_RUNS` | 4 | Kane runs per claim, retries and rewrites included |
| `RLD_FORCE` | unset | `1` ignores the fingerprint and re-runs everything |
| `RLD_HOOK` | on | `off` disables the Stop hook |

Exit codes are unchanged: 0 green, 1 red, 3 inconclusive (also: run cap hit before every claim ran), 4 infra (also: below reserve, credits exhausted, second run refused).
