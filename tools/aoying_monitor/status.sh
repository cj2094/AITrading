#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIR="$ROOT/tools/aoying_monitor"
SESSION="${AOYING_TMUX_SESSION:-aoying-monitor}"
TMUX_CONF="/exec-daemon/tmux.portal.conf"
LOG="$DIR/logs/watch.log"
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
  echo "tmux: RUNNING ($SESSION)"
  tmux_bin list-panes -t "$SESSION" -F 'pid=#{pane_pid} cmd=#{pane_current_command}'
else
  echo "tmux: STOPPED"
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
  echo "--- last 20 log lines ---"
  tail -n 20 "$LOG"
else
  echo "log: missing"
fi
