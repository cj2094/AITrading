#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIR="$ROOT/tools/aoying_monitor"
DATA_DIR="${AOYING_DATA_DIR:-$DIR/data}"
PORTFOLIO_ID="${AOYING_PORTFOLIO_ID:-5075281354358777856}"
STATE_PATH="${AOYING_STATE_PATH:-$DATA_DIR/state.json}"
HOST="${AOYING_WEB_HOST:-0.0.0.0}"
PORT="${AOYING_WEB_PORT:-8787}"

mkdir -p "$DATA_DIR"
cd "$DIR"
export PYTHONUNBUFFERED=1
exec python3 -u "$DIR/web_server.py" \
  --host "$HOST" \
  --port "$PORT" \
  --portfolio-id "$PORTFOLIO_ID" \
  --state "$STATE_PATH"
