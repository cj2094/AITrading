#!/usr/bin/env bash
# Deploy / restart the 熬鹰资本 Binance copy-trading monitor + web dashboard.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIR="$ROOT/tools/aoying_monitor"
DATA_DIR="${AOYING_DATA_DIR:-$DIR/data}"
LOG_DIR="${AOYING_LOG_DIR:-$DIR/logs}"
SESSION="${AOYING_TMUX_SESSION:-aoying-monitor}"
WEB_SESSION="${AOYING_WEB_TMUX_SESSION:-aoying-web}"
INTERVAL="${AOYING_INTERVAL:-15}"
STATE_PATH="${AOYING_STATE_PATH:-$DATA_DIR/state.json}"
PORTFOLIO_ID="${AOYING_PORTFOLIO_ID:-5075281354358777856}"
WEB_HOST="${AOYING_WEB_HOST:-0.0.0.0}"
WEB_PORT="${AOYING_WEB_PORT:-8787}"
TMUX_CONF="/exec-daemon/tmux.portal.conf"

mkdir -p "$DATA_DIR" "$LOG_DIR"
chmod +x "$DIR"/*.sh "$DIR/monitor.py" "$DIR/web_server.py"
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
echo "[deploy] watch logs=$LOG_DIR/watch.log"
echo "[deploy] web   http://${WEB_HOST}:${WEB_PORT}/  logs=$LOG_DIR/web.log"

echo "[deploy] connectivity check (once)..."
AOYING_PORTFOLIO_ID="$PORTFOLIO_ID" AOYING_STATE_PATH="$STATE_PATH" \
  python3 "$DIR/monitor.py" --portfolio-id "$PORTFOLIO_ID" --state "$STATE_PATH" once \
  | tee "$LOG_DIR/deploy_once.log" \
  | tail -n 20

export AOYING_PORTFOLIO_ID="$PORTFOLIO_ID"
export AOYING_STATE_PATH="$STATE_PATH"
export AOYING_INTERVAL="$INTERVAL"
export AOYING_DATA_DIR="$DATA_DIR"
export AOYING_LOG_DIR="$LOG_DIR"
export AOYING_WEB_HOST="$WEB_HOST"
export AOYING_WEB_PORT="$WEB_PORT"
export AOYING_QUIET="${AOYING_QUIET:-0}"

if tmux_bin has-session -t "=$SESSION" 2>/dev/null; then
  echo "[deploy] stopping existing session $SESSION"
  tmux_bin kill-session -t "$SESSION"
fi
if tmux_bin has-session -t "=$WEB_SESSION" 2>/dev/null; then
  echo "[deploy] stopping existing session $WEB_SESSION"
  tmux_bin kill-session -t "$WEB_SESSION"
fi

tmux_bin new-session -d -s "$SESSION" -c "$ROOT" -- "${SHELL:-bash}" -lc \
  "export PYTHONUNBUFFERED=1 AOYING_QUIET='$AOYING_QUIET'; exec '$DIR/start_watch.sh' >>'$LOG_DIR/watch.log' 2>&1"

tmux_bin new-session -d -s "$WEB_SESSION" -c "$ROOT" -- "${SHELL:-bash}" -lc \
  "export PYTHONUNBUFFERED=1 AOYING_WEB_HOST='$WEB_HOST' AOYING_WEB_PORT='$WEB_PORT'; exec '$DIR/start_web.sh' >>'$LOG_DIR/web.log' 2>&1"

sleep 2
ok=1
if ! tmux_bin has-session -t "=$SESSION" 2>/dev/null; then
  echo "[deploy] watch session failed" >&2
  tail -n 40 "$LOG_DIR/watch.log" 2>/dev/null || true
  ok=0
fi
if ! tmux_bin has-session -t "=$WEB_SESSION" 2>/dev/null; then
  echo "[deploy] web session failed" >&2
  tail -n 40 "$LOG_DIR/web.log" 2>/dev/null || true
  ok=0
fi
if [[ "$ok" != "1" ]]; then
  exit 1
fi

echo "[deploy] watch session: $SESSION"
echo "[deploy] web   session: $WEB_SESSION"
echo "[deploy] open: http://127.0.0.1:${WEB_PORT}/"
"$DIR/status.sh"

# Smoke the API once the web process is up.
for i in 1 2 3 4 5; do
  if curl -fsS "http://127.0.0.1:${WEB_PORT}/api/health" >/tmp/aoying_health.json 2>/dev/null; then
    echo "[deploy] health: $(cat /tmp/aoying_health.json)"
    break
  fi
  sleep 1
done
