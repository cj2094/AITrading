#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIR="$ROOT/tools/aoying_monitor"
SESSION="${AOYING_TMUX_SESSION:-aoying-monitor}"
WEB_SESSION="${AOYING_WEB_TMUX_SESSION:-aoying-web}"
WEB_PORT="${AOYING_WEB_PORT:-8787}"
TMUX_CONF="/exec-daemon/tmux.portal.conf"
LOG="$DIR/logs/watch.log"
WEB_LOG="$DIR/logs/web.log"
STATE="$DIR/data/state.json"

tmux_bin() {
  if [[ -f "$TMUX_CONF" ]]; then
    tmux -f "$TMUX_CONF" "$@"
  else
    tmux "$@"
  fi
}

echo "=== aoying monitor status ==="
if tmux_bin has-session -t "=$SESSION" 2>/dev/null; then
  echo "watch tmux: RUNNING ($SESSION)"
  tmux_bin list-panes -t "$SESSION" -F 'pid=#{pane_pid} cmd=#{pane_current_command}'
else
  echo "watch tmux: STOPPED"
fi

if tmux_bin has-session -t "=$WEB_SESSION" 2>/dev/null; then
  echo "web   tmux: RUNNING ($WEB_SESSION)  http://127.0.0.1:${WEB_PORT}/"
  tmux_bin list-panes -t "$WEB_SESSION" -F 'pid=#{pane_pid} cmd=#{pane_current_command}'
else
  echo "web   tmux: STOPPED"
fi

if [[ -f "$STATE" ]]; then
  python3 - <<PY
import json
from pathlib import Path
p = Path("$STATE")
d = json.loads(p.read_text())
detail = d.get("last_detail") or {}
print(f"state: {p}")
print(f"last_poll_at: {d.get('last_poll_at')}")
print(f"nickname: {detail.get('nickname')}")
print(f"status: {detail.get('status')}  positionShow: {detail.get('positionShow')}")
print(f"margin: {detail.get('marginBalance')}  aum: {detail.get('aumAmount')}")
print(f"seen_orders: {len(d.get('seen_orders') or [])}  seen_closes: {len(d.get('seen_positions') or [])}")
PY
else
  echo "state: missing"
fi

if [[ -f "$LOG" ]]; then
  echo "--- last watch log lines ---"
  tail -n 8 "$LOG"
fi
if [[ -f "$WEB_LOG" ]]; then
  echo "--- last web log lines ---"
  tail -n 8 "$WEB_LOG"
fi

PUBLIC_URL_FILE="$DIR/logs/public_url.txt"
if [[ -f "$PUBLIC_URL_FILE" ]]; then
  echo "public URL: $(cat "$PUBLIC_URL_FILE")"
elif [[ -f "$DIR/logs/cloudflare.log" ]]; then
  url="$(grep -Eo 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$DIR/logs/cloudflare.log" | tail -n1 || true)"
  if [[ -n "$url" ]]; then
    echo "public URL: $url"
  fi
fi
