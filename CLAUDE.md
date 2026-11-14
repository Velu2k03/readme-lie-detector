# Rules for the agent

- `demo-app/README.md` is the spec. The README wins.
- When a claim is false (FALSE_CLAIM), change the code so the claim becomes true.
- Change a README claim only when the hook says STALE_DOC, or when Velu asks.
- Never edit `claims.lock.json`, `scripts/`, `.claude/` or `rld/` to make a claim pass.
- Never write credentials (LT_USERNAME, LT_ACCESS_KEY) to any file or log.
- Do not upgrade kane-cli (pinned 0.10.4). No push without Velu's go-ahead.
