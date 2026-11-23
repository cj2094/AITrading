#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIR="$ROOT/tools/aoying_monitor"
DATA_DIR="${AOYING_DATA_DIR:-$DIR/data}"
LOG_DIR="${AOYING_LOG_DIR:-$DIR/logs}"
INTERVAL="${AOYING_INTERVAL:-15}"
STATE_PATH="${AOYING_STATE_PATH:-$DATA_DIR/state.json}"
PORTFOLIO_ID="${AOYING_PORTFOLIO_ID:-5075281354358777856}"

mkdir -p "$DATA_DIR" "$LOG_DIR"
cd "$ROOT"

args=(
  --portfolio-id "$PORTFOLIO_ID"
  --state "$STATE_PATH"
)
if [[ "${AOYING_QUIET:-0}" == "1" ]]; then
  args+=(--quiet)
fi
if [[ -n "${AOYING_WEBHOOK_URL:-}" ]]; then
  args+=(--webhook-url "$AOYING_WEBHOOK_URL")
fi
args+=(watch --interval "$INTERVAL")

export PYTHONUNBUFFERED=1
exec python3 -u "$DIR/monitor.py" "${args[@]}"
