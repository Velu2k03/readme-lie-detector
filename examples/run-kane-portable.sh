#!/usr/bin/env bash
# Portable run script for rld. Use: export RLD_RUN_SCRIPT=$PWD/examples/run-kane-portable.sh
# Same contract as the author's script: <outdir> <label> <timeout> <url> <objective>
# Needs: kane-cli on PATH and logged in, and Chrome or Chromium (set CHROME_BIN if not on PATH).
# No proxy. If your network needs one, use your own script. Not run by the author: untested.
set -u
OUT="$1"; LABEL="$2"; TO="$3"; URL="$4"; OBJ="$5"
mkdir -p "$OUT"
PORT="${RLD_CDP_PORT:-9226}"
UD=$(mktemp -d)
CHROME="${CHROME_BIN:-$(command -v google-chrome || command -v chromium || command -v chromium-browser)}"
"$CHROME" --headless=new --remote-debugging-port="$PORT" --remote-debugging-address=127.0.0.1 \
  --no-sandbox --disable-gpu --user-data-dir="$UD" about:blank >/dev/null 2>&1 &
CPID=$!
sleep 5
S=$(date +%s)
kane-cli run "$OBJ" --url "$URL" --headless --agent --timeout "$TO" --max-steps 25 \
  --cdp-endpoint "http://127.0.0.1:$PORT" > "$OUT/$LABEL.ndjson" 2> "$OUT/$LABEL.stderr" < /dev/null
EC=$?
echo "$EC" > "$OUT/$LABEL.exit"; echo $(( $(date +%s) - S )) > "$OUT/$LABEL.wall"
kill "$CPID" 2>/dev/null
rm -rf "$UD"
