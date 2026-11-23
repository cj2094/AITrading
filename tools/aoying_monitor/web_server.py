#!/usr/bin/env python3
"""HTTP dashboard for the 熬鹰资本 Binance copy-trading monitor.

Serves a static UI and JSON APIs that combine watcher state with live
Binance public lead-portfolio data.

  python3 tools/aoying_monitor/web_server.py --port 8787
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor import (  # noqa: E402
    DEFAULT_PORTFOLIO_ID,
    BinanceAPIError,
    BinanceLeadClient,
    action_label,
    fmt_num,
    fmt_ts,
    load_state,
    reconstruct_exposure,
    shanghai_now,
)

WEB_DIR = ROOT / "web"


class SnapshotCache:
    def __init__(self, ttl: float = 8.0) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._payload: dict[str, Any] | None = None
        self._fetched_at = 0.0
        self._error: str | None = None

    def get(
        self,
        client: BinanceLeadClient,
        state_path: Path,
        force: bool = False,
        page_size: int = 30,
        reconstruct_pages: int = 3,
    ) -> dict[str, Any]:
        with self._lock:
            fresh = (
                self._payload is not None
                and (time.monotonic() - self._fetched_at) < self.ttl
            )
            if fresh and not force:
                out = dict(self._payload)
                out["cache"] = {
                    "hit": True,
                    "age_sec": round(time.monotonic() - self._fetched_at, 2),
                    "ttl_sec": self.ttl,
                }
                return out

            try:
                payload = build_dashboard(
                    client,
                    state_path=state_path,
                    page_size=page_size,
                    reconstruct_pages=reconstruct_pages,
                )
                self._payload = payload
                self._fetched_at = time.monotonic()
                self._error = None
                out = dict(payload)
                out["cache"] = {"hit": False, "age_sec": 0, "ttl_sec": self.ttl}
                return out
            except Exception as exc:  # noqa: BLE001
                self._error = str(exc)
                if self._payload is not None:
                    out = dict(self._payload)
                    out["cache"] = {
                        "hit": True,
                        "stale": True,
                        "age_sec": round(time.monotonic() - self._fetched_at, 2),
                        "ttl_sec": self.ttl,
                        "error": self._error,
                    }
                    return out
                raise


def watcher_running(session: str = "aoying-monitor") -> bool:
    conf = "/exec-daemon/tmux.portal.conf"
    cmd = ["tmux"]
    if Path(conf).exists():
        cmd.extend(["-f", conf])
    cmd.extend(["has-session", "-t", f"={session}"])
    try:
        return subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    except OSError:
        return False


def serialize_order(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": order.get("orderTime") or order.get("orderUpdateTime"),
        "timeText": fmt_ts(order.get("orderTime") or order.get("orderUpdateTime")),
        "symbol": order.get("symbol"),
        "side": order.get("side"),
        "positionSide": order.get("positionSide"),
        "action": action_label(order),
        "qty": order.get("executedQty"),
        "qtyText": fmt_num(order.get("executedQty")),
        "price": order.get("avgPrice"),
        "priceText": fmt_num(order.get("avgPrice"), 6),
        "pnl": order.get("totalPnl"),
        "pnlText": fmt_num(order.get("totalPnl"), 2),
        "type": order.get("type"),
    }


def serialize_position(pos: dict[str, Any]) -> dict[str, Any]:
    roi = pos.get("roi")
    try:
        roi_pct = float(roi) * 100 if roi is not None else None
    except (TypeError, ValueError):
        roi_pct = None
    return {
        "closed": pos.get("closed") or pos.get("updateTime"),
        "closedText": fmt_ts(pos.get("closed") or pos.get("updateTime")),
        "symbol": pos.get("symbol"),
        "side": pos.get("side"),
        "status": pos.get("status"),
        "volume": pos.get("closedVolume"),
        "volumeText": fmt_num(pos.get("closedVolume")),
        "avgCost": pos.get("avgCost"),
        "avgClosePrice": pos.get("avgClosePrice"),
        "pnl": pos.get("closingPnl"),
        "pnlText": fmt_num(pos.get("closingPnl"), 2),
        "roi": roi,
        "roiText": f"{fmt_num(roi_pct, 2)}%" if roi_pct is not None else "-",
        "leverage": pos.get("leverage"),
    }


def serialize_exposure(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "qty": row.get("qty"),
        "qtyText": fmt_num(row.get("qty")),
        "avgEntryEst": row.get("avg_entry_est"),
        "avgEntryEstText": fmt_num(row.get("avg_entry_est"), 6),
        "lastPrice": row.get("last_price"),
        "lastPriceText": fmt_num(row.get("last_price"), 6),
        "lastTime": row.get("last_time"),
        "lastTimeText": fmt_ts(row.get("last_time")),
        "orders": row.get("orders"),
    }


def build_dashboard(
    client: BinanceLeadClient,
    state_path: Path,
    page_size: int = 30,
    reconstruct_pages: int = 3,
) -> dict[str, Any]:
    detail = client.detail()
    orders = (client.order_history(page=1, page_size=page_size).get("list") or [])[:page_size]
    positions = (
        client.position_history(page=1, page_size=min(page_size, 20)).get("list") or []
    )[: min(page_size, 20)]

    exposure: list[dict[str, Any]] = []
    exposure_error: str | None = None
    try:
        exposure = reconstruct_exposure(client, page_size, reconstruct_pages)
    except BinanceAPIError as exc:
        exposure_error = str(exc)

    state = load_state(state_path) if state_path.exists() else {}
    try:
        profit_share = float(detail.get("profitSharingRate") or 0)
    except (TypeError, ValueError):
        profit_share = 0.0

    return {
        "generatedAt": shanghai_now().isoformat(),
        "generatedAtText": shanghai_now().strftime("%Y-%m-%d %H:%M:%S CST"),
        "watcher": {
            "running": watcher_running(os.environ.get("AOYING_TMUX_SESSION", "aoying-monitor")),
            "statePath": str(state_path),
            "lastPollAt": state.get("last_poll_at"),
            "seenOrders": len(state.get("seen_orders") or []),
            "seenCloses": len(state.get("seen_positions") or []),
        },
        "portfolio": {
            "id": detail.get("leadPortfolioId") or client.portfolio_id,
            "name": detail.get("nickname") or "熬鹰资本",
            "status": detail.get("status"),
            "positionShow": detail.get("positionShow"),
            "description": detail.get("description") or detail.get("descTranslate"),
            "aum": detail.get("aumAmount"),
            "aumText": fmt_num(detail.get("aumAmount")),
            "marginBalance": detail.get("marginBalance"),
            "marginText": fmt_num(detail.get("marginBalance")),
            "copierPnl": detail.get("copierPnl"),
            "copierPnlText": fmt_num(detail.get("copierPnl")),
            "currentCopyCount": detail.get("currentCopyCount"),
            "maxCopyCount": detail.get("maxCopyCount"),
            "totalCopyCount": detail.get("totalCopyCount"),
            "profitSharingRate": profit_share,
            "profitSharingText": f"{fmt_num(profit_share, 2)}%",
            "lastTradeTime": detail.get("lastTradeTime"),
            "lastTradeText": fmt_ts(detail.get("lastTradeTime")),
            "binanceUrl": (
                "https://www.binance.com/zh-CN/copy-trading/lead-details/"
                f"{detail.get('leadPortfolioId') or client.portfolio_id}"
            ),
        },
        "orders": [serialize_order(o) for o in orders],
        "closedPositions": [serialize_position(p) for p in positions],
        "exposure": [serialize_exposure(r) for r in exposure],
        "exposureError": exposure_error,
        "notes": [
            "带单员隐藏了实时仓位；敞口由公开成交推算，仅供参考。",
            "数据来自币安公开 lead-portfolio 接口，无需 API Key。",
        ],
    }


def make_handler(
    client: BinanceLeadClient,
    state_path: Path,
    cache: SnapshotCache,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "AoyingMonitor/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            stamp = shanghai_now().strftime("%H:%M:%S")
            print(f"[{stamp}] {self.address_string()} {fmt % args}")

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, payload: Any) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(code, raw, "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path in {"/", "/index.html"}:
                index = WEB_DIR / "index.html"
                self._send(200, index.read_bytes(), "text/html; charset=utf-8")
                return

            if path.startswith("/static/"):
                rel = path[len("/static/") :]
                target = (WEB_DIR / rel).resolve()
                if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
                    self._json(404, {"error": "not found"})
                    return
                ctype = "text/plain; charset=utf-8"
                if target.suffix == ".css":
                    ctype = "text/css; charset=utf-8"
                elif target.suffix == ".js":
                    ctype = "application/javascript; charset=utf-8"
                elif target.suffix == ".svg":
                    ctype = "image/svg+xml"
                self._send(200, target.read_bytes(), ctype)
                return

            if path == "/api/health":
                self._json(
                    200,
                    {
                        "ok": True,
                        "time": shanghai_now().isoformat(),
                        "watcherRunning": watcher_running(
                            os.environ.get("AOYING_TMUX_SESSION", "aoying-monitor")
                        ),
                    },
                )
                return

            if path == "/api/status":
                state = load_state(state_path) if state_path.exists() else {}
                self._json(
                    200,
                    {
                        "watcherRunning": watcher_running(
                            os.environ.get("AOYING_TMUX_SESSION", "aoying-monitor")
                        ),
                        "state": {
                            "lastPollAt": state.get("last_poll_at"),
                            "lastDetail": state.get("last_detail"),
                            "seenOrders": len(state.get("seen_orders") or []),
                            "seenCloses": len(state.get("seen_positions") or []),
                        },
                        "generatedAtText": shanghai_now().strftime(
                            "%Y-%m-%d %H:%M:%S CST"
                        ),
                    },
                )
                return

            if path == "/api/dashboard":
                force = qs.get("fresh", ["0"])[0] in {"1", "true", "yes"}
                try:
                    payload = cache.get(client, state_path, force=force)
                    self._json(200, payload)
                except Exception as exc:  # noqa: BLE001
                    self._json(502, {"error": str(exc)})
                return

            self._json(404, {"error": "not found"})

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="熬鹰资本带单监控网页")
    parser.add_argument("--host", default=os.environ.get("AOYING_WEB_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AOYING_WEB_PORT", "8787")),
    )
    parser.add_argument(
        "--portfolio-id",
        default=os.environ.get("AOYING_PORTFOLIO_ID", DEFAULT_PORTFOLIO_ID),
    )
    parser.add_argument(
        "--state",
        default=os.environ.get(
            "AOYING_STATE_PATH", str(ROOT / "data" / "state.json")
        ),
    )
    parser.add_argument(
        "--cache-ttl",
        type=float,
        default=float(os.environ.get("AOYING_WEB_CACHE_TTL", "8")),
    )
    args = parser.parse_args(argv)

    if not (WEB_DIR / "index.html").exists():
        raise SystemExit(f"missing UI files under {WEB_DIR}")

    client = BinanceLeadClient(str(args.portfolio_id), min_interval=1.0)
    cache = SnapshotCache(ttl=float(args.cache_ttl))
    handler = make_handler(client, Path(args.state), cache)
    server = ThreadingHTTPServer((args.host, int(args.port)), handler)
    print(
        f"aoying web listening on http://{args.host}:{args.port} "
        f"(portfolio={args.portfolio_id})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
