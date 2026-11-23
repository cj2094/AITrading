#!/usr/bin/env bash
# Expose the local dashboard (default :8787) via Cloudflare quick tunnel.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIR="$ROOT/tools/aoying_monitor"
LOG_DIR="${AOYING_LOG_DIR:-$DIR/logs}"
SESSION="${AOYING_TUNNEL_TMUX_SESSION:-aoying-cf}"
PORT="${AOYING_WEB_PORT:-8787}"
TMUX_CONF="/exec-daemon/tmux.portal.conf"
CF_BIN="${AOYING_CLOUDFLARED:-}"

mkdir -p "$LOG_DIR"

if [[ -z "$CF_BIN" ]]; then
  if command -v cloudflared >/dev/null 2>&1; then
    CF_BIN="$(command -v cloudflared)"
  elif [[ -x /tmp/cloudflared ]]; then
    CF_BIN=/tmp/cloudflared
  else
    echo "cloudflared not found; downloading..." >&2
    curl -fsSL -o /tmp/cloudflared \
      https://github.com/cloudflare/cloudflared/releases/download/2025.2.1/cloudflared-linux-amd64
    chmod +x /tmp/cloudflared
    CF_BIN=/tmp/cloudflared
  fi
fi

tmux_bin() {
  if [[ -f "$TMUX_CONF" ]]; then
    tmux -f "$TMUX_CONF" "$@"
  else
    tmux "$@"
  fi
}

if ! curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
  echo "dashboard not reachable on :${PORT}; start it first: ./tools/aoying_monitor/deploy.sh" >&2
  exit 1
fi

if tmux_bin has-session -t "=$SESSION" 2>/dev/null; then
  tmux_bin kill-session -t "$SESSION"
fi

: > "$LOG_DIR/cloudflare.log"
tmux_bin new-session -d -s "$SESSION" -c "$ROOT" -- bash -lc \
  "exec '$CF_BIN' tunnel --url 'http://127.0.0.1:${PORT}' --no-autoupdate 2>&1 | tee '$LOG_DIR/cloudflare.log'"

echo "[tunnel] waiting for public URL..."
url=""
for _ in $(seq 1 30); do
  url="$(grep -Eo 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$LOG_DIR/cloudflare.log" | tail -n1 || true)"
  if [[ -n "$url" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$url" ]]; then
  echo "[tunnel] failed; see $LOG_DIR/cloudflare.log" >&2
  exit 1
fi

echo "[tunnel] public URL: $url"
echo "$url" > "$LOG_DIR/public_url.txt"
echo "[tunnel] stop: tmux -f $TMUX_CONF kill-session -t $SESSION"
