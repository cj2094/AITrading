#!/usr/bin/env bash
# Deploy / restart the 熬鹰资本 Binance copy-trading monitor as a tmux service.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIR="$ROOT/tools/aoying_monitor"
DATA_DIR="${AOYING_DATA_DIR:-$DIR/data}"
LOG_DIR="${AOYING_LOG_DIR:-$DIR/logs}"
SESSION="${AOYING_TMUX_SESSION:-aoying-monitor}"
INTERVAL="${AOYING_INTERVAL:-15}"
STATE_PATH="${AOYING_STATE_PATH:-$DATA_DIR/state.json}"
PORTFOLIO_ID="${AOYING_PORTFOLIO_ID:-5075281354358777856}"
TMUX_CONF="/exec-daemon/tmux.portal.conf"

mkdir -p "$DATA_DIR" "$LOG_DIR"
chmod +x "$DIR"/*.sh "$DIR/monitor.py"
cd "$ROOT"

tmux_bin() {
  if [[ -f "$TMUX_CONF" ]]; then
    tmux -f "$TMUX_CONF" "$@"
  else
    tmux "$@"
  fi
}

echo "[deploy] portfolio=$PORTFOLIO_ID interval=${INTERVAL}s"
echo "[deploy] state=$STATE_PATH"
echo "[deploy] logs=$LOG_DIR/watch.log"
echo "[deploy] session=$SESSION"

echo "[deploy] connectivity check (once)..."
AOYING_PORTFOLIO_ID="$PORTFOLIO_ID" AOYING_STATE_PATH="$STATE_PATH" \
  python3 "$DIR/monitor.py" --portfolio-id "$PORTFOLIO_ID" --state "$STATE_PATH" once \
  | tee "$LOG_DIR/deploy_once.log" \
  | tail -n 35

if tmux_bin has-session -t "=$SESSION" 2>/dev/null; then
  echo "[deploy] stopping existing session $SESSION"
  tmux_bin kill-session -t "$SESSION"
fi

# Fresh state for watch bootstrap after deploy check used the same state file.
# Keep seen_* from once so watch does not re-alert historical fills.
export AOYING_PORTFOLIO_ID PORTFOLIO_ID
export AOYING_STATE_PATH="$STATE_PATH"
export AOYING_INTERVAL="$INTERVAL"
export AOYING_DATA_DIR="$DATA_DIR"
export AOYING_LOG_DIR="$LOG_DIR"

# Drop --quiet for the running service so heartbeat lines land in the log;
# override with AOYING_QUIET=1 if desired.
export AOYING_QUIET="${AOYING_QUIET:-0}"
tmux_bin new-session -d -s "$SESSION" -c "$ROOT" -- "${SHELL:-bash}" -lc \
  "export PYTHONUNBUFFERED=1 AOYING_QUIET='$AOYING_QUIET'; exec '$DIR/start_watch.sh' >>'$LOG_DIR/watch.log' 2>&1"

sleep 1.5
if ! tmux_bin has-session -t "=$SESSION" 2>/dev/null; then
  echo "[deploy] failed to start tmux session" >&2
  tail -n 50 "$LOG_DIR/watch.log" 2>/dev/null || true
  exit 1
fi

echo "[deploy] running in tmux session: $SESSION"
echo "[deploy] attach: tmux -f $TMUX_CONF attach -t $SESSION"
echo "[deploy] logs:   tail -f $LOG_DIR/watch.log"
echo "[deploy] status: $DIR/status.sh"
echo "[deploy] stop:   tmux -f $TMUX_CONF kill-session -t $SESSION"
"$DIR/status.sh"
