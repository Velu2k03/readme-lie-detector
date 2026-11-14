#!/usr/bin/env bash
# Build and serve the app, then run `rld gate`. Exit code is rld gate's (0/1/3/4), or 6 when the build fails.
# Env: RLD_PORT (4173), RLD_APP_DIR (demo-app), RLD_README, RLD_LOCK, RLD_PYTHON, RLD_OUT (report/).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 4
PORT="${RLD_PORT:-4173}"
APP_DIR="${RLD_APP_DIR:-demo-app}"
README="${RLD_README:-$APP_DIR/README.md}"
LOCK="${RLD_LOCK:-claims.lock.json}"
PY="${RLD_PYTHON:-python3}"
OUT="${RLD_OUT:-report/}"

[ -f "$README" ] || { echo "README not found: $README" >&2; exit 4; }
SERVE_DIR="$APP_DIR"
if [ -f "$APP_DIR/package.json" ]; then
  (cd "$APP_DIR" && npm run build) >&2 || exit 6
  SERVE_DIR="$APP_DIR/dist"
fi

"$PY" -m http.server "$PORT" --bind 127.0.0.1 --directory "$SERVE_DIR" >/dev/null 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
for _ in $(seq 1 50); do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break
  sleep 0.2
done
curl -s -o /dev/null "http://127.0.0.1:$PORT/" || { echo "server did not start on port $PORT" >&2; exit 4; }

"$PY" -m rld gate --url "http://127.0.0.1:$PORT/" --readme "$README" --lock "$LOCK" \
  --app-dir "$APP_DIR/" --out "$OUT" --failed-first --stop-on-red
