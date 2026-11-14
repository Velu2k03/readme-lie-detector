#!/usr/bin/env bash
# Claude Code Stop hook. rld gate exit 1 (a red claim) -> exit 2, which blocks the Stop; red claims go to stderr.
# Everything else (green, inconclusive, infra) -> exit 0. RLD_HOOK=off disables it.
# stop_hook_active=false means a fresh stop request, so the blocked-round counter restarts.
# After MAX_BLOCKS blocked rounds the turn is released with a warning.
set -uo pipefail
[ "${RLD_HOOK:-on}" = "off" ] && exit 0
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/..}" || exit 0
MAX_BLOCKS=3
PY="${RLD_PYTHON:-python3}"
OUT="${RLD_OUT:-report/}"

input="$(cat)"
read -r active sid < <("$PY" -c 'import json,sys
try: d=json.loads(sys.stdin.read())
except Exception: d={}
print(str(bool(d.get("stop_hook_active"))).lower(), "".join(c for c in str(d.get("session_id","x")) if c.isalnum() or c in "-_") or "x")' <<<"$input")
mkdir -p .rld/hook
state=".rld/hook/$sid.count"
[ "$active" = "true" ] || echo 0 > "$state"
count="$(cat "$state" 2>/dev/null || echo 0)"

log=".rld/hook/last-gate.log"
scripts/serve-and-check.sh >"$log" 2>&1
rc=$?

case "$rc" in
  0) echo 0 > "$state"; exit 0 ;;
  1|6)
    msg="$("$PY" - "$OUT" "$rc" "$log" <<'PYEOF'
import json, sys
out, rc, log = sys.argv[1:4]
if rc == "6":
    print("README Lie Detector: the app build failed. Fix the build errors:")
    print(open(log, errors="replace").read()[-1500:])
    sys.exit()
try:
    d = json.load(open(out.rstrip("/") + "/results.json"))
except Exception:
    sys.exit()
red = [r for r in d["results"] if r["verdict"] in ("FALSE_CLAIM", "STALE_DOC") and not r.get("carried")]
if not red:
    sys.exit()
print(f"README Lie Detector: {len(red)} README claim(s) failed in a real browser run. Fix them, then finish again.")
for r in red:
    print(f'- {r["id"]} {r["verdict"]} (README line {r.get("readme_line")}): "{r.get("readme_quote")}"')
    print(f'  Kane saw: {r.get("one_liner")}')
    print(f'  Fix: {r.get("fix_hint")}')
print(f"Report: {out}index.html")
PYEOF
)"
    if [ -z "$msg" ]; then
      echo "README Lie Detector: gate exit $rc but no red claim in results.json; not blocking. See $log" >&2
      exit 0
    fi
    count=$((count + 1)); echo "$count" > "$state"
    if [ "$count" -gt "$MAX_BLOCKS" ]; then
      echo 0 > "$state"
      echo "README Lie Detector WARNING: released the turn after $MAX_BLOCKS blocked rounds; claims still red:" >&2
      echo "$msg" >&2
      exit 0
    fi
    echo "$msg" >&2
    exit 2 ;;
  *)
    echo "README Lie Detector: gate exit $rc (inconclusive or infra); not blocking. See $log" >&2
    exit 0 ;;
esac
