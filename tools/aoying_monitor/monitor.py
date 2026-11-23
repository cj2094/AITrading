#!/usr/bin/env python3
"""Monitor Binance copy-trading lead portfolio: 熬鹰资本.

Polls Binance public lead-portfolio APIs (no API key) for:
  - portfolio detail (AUM / margin / last trade)
  - order history (opens, adds, reduces, closes)
  - closed position history
  - trade ticks

Open positions for this lead are hidden (`positionShow=false`). The tool
reconstructs approximate net exposure from recent orders relative to the
latest "All Closed" rounds so you can still watch activity.

Examples:
  python3 tools/aoying_monitor/monitor.py once
  python3 tools/aoying_monitor/monitor.py watch --interval 15
  python3 tools/aoying_monitor/monitor.py watch --webhook-url "$HOOK"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

DEFAULT_PORTFOLIO_ID = "5075281354358777856"
DEFAULT_NAME = "熬鹰资本"
LEAD_BASE = (
    "https://www.binance.com/bapi/futures/v1/friendly/"
    "future/copy-trade/lead-portfolio"
)
SHANGHAI = timezone(timedelta(hours=8))

USER_AGENT = (
    "Mozilla/5.0 (compatible; AITrading-AoyingMonitor/1.0; "
    "+https://github.com/cj2094/AITrading)"
)


class BinanceAPIError(RuntimeError):
    pass


def shanghai_now() -> datetime:
    return datetime.now(SHANGHAI)


def fmt_ts(ms: int | float | None) -> str:
    if ms is None:
        return "-"
    return datetime.fromtimestamp(ms / 1000, tz=SHANGHAI).strftime(
        "%Y-%m-%d %H:%M:%S CST"
    )


def fmt_num(value: Any, digits: int = 4) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "-"
    if abs(n) >= 1000:
        return f"{n:,.2f}"
    return f"{n:.{digits}f}"


@dataclass
class MonitorConfig:
    portfolio_id: str = DEFAULT_PORTFOLIO_ID
    interval: float = 15.0
    page_size: int = 50
    state_path: Path = Path("tools/aoying_monitor/state.json")
    webhook_url: str | None = None
    quiet: bool = False
    reconstruct_pages: int = 5


class BinanceLeadClient:
    def __init__(
        self,
        portfolio_id: str,
        timeout: float = 20.0,
        min_interval: float = 1.0,
    ) -> None:
        self.portfolio_id = portfolio_id
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_request_at = 0.0

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "clienttype": "web",
            "Origin": "https://www.binance.com",
            "Referer": (
                "https://www.binance.com/zh-CN/copy-trading/lead-details/"
                f"{self.portfolio_id}"
            ),
        }

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        retries: int = 4,
    ) -> Any:
        url = f"{LEAD_BASE}/{path.lstrip('/')}"
        if query:
            qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in query.items())
            url = f"{url}?{qs}"
        data = None if body is None else json.dumps(body).encode("utf-8")

        last_error: Exception | None = None
        for attempt in range(retries):
            self._throttle()
            req = urllib.request.Request(
                url, data=data, headers=self._headers(), method=method.upper()
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                self._last_request_at = time.monotonic()
            except urllib.error.HTTPError as exc:
                self._last_request_at = time.monotonic()
                detail = exc.read().decode("utf-8", errors="replace")
                last_error = BinanceAPIError(
                    f"HTTP {exc.code} {path}: {detail[:300]}"
                )
                time.sleep(min(2 ** attempt, 20))
                continue
            except urllib.error.URLError as exc:
                self._last_request_at = time.monotonic()
                last_error = BinanceAPIError(f"network error {path}: {exc}")
                time.sleep(min(2 ** attempt, 20))
                continue

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise BinanceAPIError(
                    f"invalid JSON from {path}: {raw[:200]}"
                ) from exc

            code = str(payload.get("code") or "") if isinstance(payload, dict) else ""
            busy = code in {"11012005", "90801003"} or (
                isinstance(payload, dict) and payload.get("success") is False
                and "busy" in str(payload.get("message") or "").lower()
            )
            if busy and attempt + 1 < retries:
                time.sleep(min(5 * (attempt + 1), 30))
                last_error = BinanceAPIError(
                    f"API busy {path}: code={code} msg={payload.get('message')}"
                )
                continue

            if isinstance(payload, dict) and payload.get("success") is False:
                raise BinanceAPIError(
                    f"API failure {path}: code={payload.get('code')} "
                    f"msg={payload.get('message')}"
                )
            if isinstance(payload, dict) and "data" in payload:
                return payload["data"]
            return payload

        assert last_error is not None
        raise last_error

    def detail(self) -> dict[str, Any]:
        return self._request("GET", "detail", query={"portfolioId": self.portfolio_id})

    def order_history(self, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        return self._request(
            "POST",
            "order-history",
            body={
                "portfolioId": self.portfolio_id,
                "pageNumber": page,
                "pageSize": page_size,
            },
        )

    def position_history(self, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        return self._request(
            "POST",
            "position-history",
            body={
                "portfolioId": self.portfolio_id,
                "pageNumber": page,
                "pageSize": page_size,
            },
        )

    def trade_history(self, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        return self._request(
            "POST",
            "trade-history",
            body={
                "portfolioId": self.portfolio_id,
                "pageNumber": page,
                "pageSize": page_size,
            },
        )

    def transfer_history(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        return self._request(
            "POST",
            "transfer-history",
            body={
                "portfolioId": self.portfolio_id,
                "pageNumber": page,
                "pageSize": page_size,
            },
        )


def order_key(order: dict[str, Any]) -> str:
    return "|".join(
        [
            str(order.get("symbol")),
            str(order.get("side")),
            str(order.get("positionSide")),
            str(order.get("orderTime")),
            str(order.get("orderUpdateTime")),
            str(order.get("executedQty")),
            str(order.get("avgPrice")),
            str(order.get("type")),
            str(order.get("totalPnl")),
        ]
    )


def position_key(pos: dict[str, Any]) -> str:
    return "|".join(
        [
            str(pos.get("positionId") or pos.get("id")),
            str(pos.get("symbol")),
            str(pos.get("side")),
            str(pos.get("status")),
            str(pos.get("closed") or pos.get("updateTime")),
            str(pos.get("closedVolume")),
            str(pos.get("closingPnl")),
        ]
    )


def transfer_key(item: dict[str, Any]) -> str:
    return "|".join(
        [
            str(item.get("id") or item.get("tranId") or ""),
            str(item.get("time") or item.get("createTime") or ""),
            str(item.get("amount") or item.get("qty") or ""),
            str(item.get("type") or item.get("transferType") or ""),
            str(item.get("asset") or item.get("coin") or ""),
        ]
    )


def signed_qty_delta(order: dict[str, Any]) -> float:
    """Signed base-qty change for reconstructed net exposure.

    Hedge-mode convention on Binance futures:
      BUY LONG / SELL SHORT  -> open/add  (+qty)
      SELL LONG / BUY SHORT  -> reduce    (-qty)
    """
    try:
        qty = float(order.get("executedQty") or 0)
    except (TypeError, ValueError):
        return 0.0
    side = str(order.get("side") or "").upper()
    pos_side = str(order.get("positionSide") or "").upper()
    if pos_side in {"", "BOTH"}:
        # one-way: BUY increases, SELL decreases
        return qty if side == "BUY" else -qty
    if pos_side == "LONG":
        return qty if side == "BUY" else -qty
    if pos_side == "SHORT":
        return qty if side == "SELL" else -qty
    return 0.0


def action_label(order: dict[str, Any]) -> str:
    side = str(order.get("side") or "").upper()
    pos_side = str(order.get("positionSide") or "").upper()
    pnl = float(order.get("totalPnl") or 0)
    if pos_side == "LONG":
        if side == "BUY":
            return "开多/加多"
        return "平多/减多" if pnl != 0 or side == "SELL" else "卖出"
    if pos_side == "SHORT":
        if side == "SELL":
            return "开空/加空"
        return "平空/减空"
    return f"{side} {pos_side}".strip()


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "seen_orders": [],
            "seen_positions": [],
            "seen_transfers": [],
            "bootstrap": True,
        }
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("seen_orders", [])
    data.setdefault("seen_positions", [])
    data.setdefault("seen_transfers", [])
    data.setdefault("bootstrap", False)
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)


def trim_seen(keys: list[str], limit: int = 2000) -> list[str]:
    if len(keys) <= limit:
        return keys
    return keys[-limit:]


def post_webhook(url: str, text: str) -> None:
    # Compatible with Slack/Discord/Feishu-style incoming webhooks that accept {"text": ...}
    # Also supports Telegram Bot API style if URL already includes sendMessage.
    payload: dict[str, Any]
    if "api.telegram.org" in url and "sendMessage" in url:
        payload = {"text": text, "disable_web_page_preview": True}
    else:
        payload = {"text": text, "msg_type": "text", "content": {"text": text}}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def print_detail(detail: dict[str, Any]) -> None:
    name = detail.get("nickname") or DEFAULT_NAME
    print("=" * 64)
    print(f"{name}  |  portfolio {detail.get('leadPortfolioId') or detail.get('portfolioId')}")
    print(f"状态: {detail.get('status')}  仓位公开: {detail.get('positionShow')}")
    print(
        f"跟单人数: {detail.get('currentCopyCount')}/{detail.get('maxCopyCount')}  "
        f"累计跟单: {detail.get('totalCopyCount')}"
    )
    print(
        f"AUM: {fmt_num(detail.get('aumAmount'))} USDT  "
        f"带单保证金: {fmt_num(detail.get('marginBalance'))} USDT"
    )
    # Binance returns profitSharingRate as percent string, e.g. "10.00"
    try:
        profit_share = float(detail.get("profitSharingRate") or 0)
    except (TypeError, ValueError):
        profit_share = 0.0
    print(
        f"跟单者盈亏: {fmt_num(detail.get('copierPnl'))} USDT  "
        f"分润: {fmt_num(profit_share, 2)}%"
    )
    print(f"最近成交: {fmt_ts(detail.get('lastTradeTime'))}")
    print(f"刷新时间: {shanghai_now().strftime('%Y-%m-%d %H:%M:%S CST')}")
    print("=" * 64)


def print_orders(orders: list[dict[str, Any]], title: str = "最近订单") -> None:
    print(f"\n{title} ({len(orders)})")
    if not orders:
        print("  (无)")
        return
    for order in orders:
        print(
            f"  {fmt_ts(order.get('orderTime'))}  "
            f"{order.get('symbol'):<14}  {action_label(order):<8}  "
            f"qty={fmt_num(order.get('executedQty'), 4)}  "
            f"px={fmt_num(order.get('avgPrice'), 6)}  "
            f"pnl={fmt_num(order.get('totalPnl'), 2)}  "
            f"{order.get('type')}"
        )


def print_positions(positions: list[dict[str, Any]], title: str = "最近平仓") -> None:
    print(f"\n{title} ({len(positions)})")
    if not positions:
        print("  (无)")
        return
    for pos in positions:
        print(
            f"  {fmt_ts(pos.get('closed') or pos.get('updateTime'))}  "
            f"{pos.get('symbol'):<14}  {pos.get('side'):<5}  "
            f"status={pos.get('status'):<10}  "
            f"vol={fmt_num(pos.get('closedVolume'), 4)}  "
            f"pnl={fmt_num(pos.get('closingPnl'), 2)}  "
            f"roi={fmt_num(float(pos.get('roi') or 0) * 100, 2)}%  "
            f"lev={pos.get('leverage')}x"
        )


def reconstruct_exposure(
    client: BinanceLeadClient, page_size: int, pages: int
) -> list[dict[str, Any]]:
    """Approximate open exposure while positionShow is false.

    For each symbol+side, find the newest All Closed time, then sum signed
    order qty after that close. Non-zero remainder ≈ still open.
    """
    closes: dict[tuple[str, str], int] = {}
    for page in range(1, pages + 1):
        data = client.position_history(page=page, page_size=page_size)
        for pos in data.get("list") or []:
            status = str(pos.get("status") or "")
            if status not in {"All Closed", "Closed"}:
                continue
            symbol = str(pos.get("symbol") or "")
            side = str(pos.get("side") or "").upper()
            closed_at = int(pos.get("closed") or pos.get("updateTime") or 0)
            key = (symbol, side)
            if closed_at and closed_at > closes.get(key, 0):
                closes[key] = closed_at

    exposure: dict[tuple[str, str], dict[str, Any]] = {}
    for page in range(1, pages + 1):
        data = client.order_history(page=page, page_size=page_size)
        for order in data.get("list") or []:
            symbol = str(order.get("symbol") or "")
            pos_side = str(order.get("positionSide") or "").upper()
            if pos_side == "BOTH":
                pos_side = "LONG" if signed_qty_delta(order) >= 0 else "SHORT"
            # position-history uses Long/Short title case
            close_side = "LONG" if pos_side == "LONG" else "SHORT"
            # Binance position history side is "Long"/"Short"
            close_key_candidates = [
                (symbol, "LONG"),
                (symbol, "SHORT"),
                (symbol, "Long"),
                (symbol, "Short"),
            ]
            baseline = 0
            for ck in close_key_candidates:
                if ck[1].upper() != close_side:
                    continue
                baseline = max(baseline, closes.get(ck, 0), closes.get((symbol, ck[1]), 0))
            # normalize lookup
            for (sym, side), ts in closes.items():
                if sym == symbol and side.upper() == close_side:
                    baseline = max(baseline, ts)

            order_time = int(order.get("orderTime") or order.get("orderUpdateTime") or 0)
            if baseline and order_time <= baseline:
                continue
            delta = signed_qty_delta(order)
            if delta == 0:
                continue
            key = (symbol, close_side)
            slot = exposure.setdefault(
                key,
                {
                    "symbol": symbol,
                    "side": close_side,
                    "qty": 0.0,
                    "notional": 0.0,
                    "last_price": None,
                    "last_time": 0,
                    "orders": 0,
                },
            )
            qty = float(order.get("executedQty") or 0)
            px = float(order.get("avgPrice") or 0)
            slot["qty"] += delta
            slot["notional"] += abs(qty) * px * (1 if delta > 0 else -1)
            slot["last_price"] = px
            slot["last_time"] = max(slot["last_time"], order_time)
            slot["orders"] += 1

    rows: list[dict[str, Any]] = []
    for slot in exposure.values():
        qty = slot["qty"]
        if abs(qty) < 1e-12:
            continue
        avg = abs(slot["notional"] / qty) if qty else None
        rows.append(
            {
                "symbol": slot["symbol"],
                "side": slot["side"],
                "qty": qty,
                "avg_entry_est": avg,
                "last_price": slot["last_price"],
                "last_time": slot["last_time"],
                "orders": slot["orders"],
            }
        )
    rows.sort(key=lambda r: r["last_time"], reverse=True)
    return rows


def print_exposure(rows: list[dict[str, Any]]) -> None:
    print("\n估算未平仓敞口（由成交推算，非币安实时仓位）")
    if not rows:
        print("  (当前推算为空仓，或最近几页订单不足以还原)")
        return
    for row in rows:
        print(
            f"  {fmt_ts(row['last_time'])}  "
            f"{row['symbol']:<14}  {row['side']:<5}  "
            f"qty={fmt_num(row['qty'], 4)}  "
            f"est_avg={fmt_num(row['avg_entry_est'], 6)}  "
            f"last_px={fmt_num(row['last_price'], 6)}  "
            f"orders={row['orders']}"
        )


def format_order_alert(name: str, order: dict[str, Any]) -> str:
    return (
        f"[{name}] {action_label(order)} {order.get('symbol')}\n"
        f"时间: {fmt_ts(order.get('orderTime'))}\n"
        f"方向: {order.get('side')} / {order.get('positionSide')}\n"
        f"数量: {fmt_num(order.get('executedQty'))} @ {fmt_num(order.get('avgPrice'), 6)}\n"
        f"成交盈亏: {fmt_num(order.get('totalPnl'), 2)} USDT\n"
        f"类型: {order.get('type')}"
    )


def format_position_alert(name: str, pos: dict[str, Any]) -> str:
    return (
        f"[{name}] 仓位完结 {pos.get('symbol')} {pos.get('side')}\n"
        f"状态: {pos.get('status')}\n"
        f"平仓时间: {fmt_ts(pos.get('closed') or pos.get('updateTime'))}\n"
        f"量: {fmt_num(pos.get('closedVolume'))}  "
        f"均开 {fmt_num(pos.get('avgCost'), 6)} → 均平 {fmt_num(pos.get('avgClosePrice'), 6)}\n"
        f"盈亏: {fmt_num(pos.get('closingPnl'), 2)} USDT  "
        f"ROI {fmt_num(float(pos.get('roi') or 0) * 100, 2)}%  "
        f"杠杆 {pos.get('leverage')}x"
    )


def notify(cfg: MonitorConfig, text: str) -> None:
    if not cfg.quiet:
        print("\n*** ALERT ***")
        print(text)
        print("*************\n")
    if not cfg.webhook_url:
        return
    try:
        post_webhook(cfg.webhook_url, text)
    except Exception as exc:  # noqa: BLE001 - keep monitor alive
        print(f"[warn] webhook failed: {exc}", file=sys.stderr)


def snapshot(cfg: MonitorConfig, client: BinanceLeadClient) -> None:
    detail = client.detail()
    orders = (client.order_history(page=1, page_size=cfg.page_size).get("list") or [])
    positions = (
        client.position_history(page=1, page_size=min(cfg.page_size, 20)).get("list") or []
    )
    print_detail(detail)
    print_orders(orders[:15])
    print_positions(positions[:10])
    try:
        exposure = reconstruct_exposure(client, cfg.page_size, cfg.reconstruct_pages)
        print_exposure(exposure)
    except BinanceAPIError as exc:
        print(f"\n[warn] 敞口推算失败: {exc}", file=sys.stderr)
    print(
        "\n提示: 该带单员隐藏了实时仓位；本工具通过公开 order-history / "
        "position-history 监控成交与平仓事件。"
    )


def poll_once(cfg: MonitorConfig, client: BinanceLeadClient, state: dict[str, Any]) -> dict[str, Any]:
    detail = client.detail()
    name = detail.get("nickname") or DEFAULT_NAME
    orders = client.order_history(page=1, page_size=cfg.page_size).get("list") or []
    positions = client.position_history(page=1, page_size=cfg.page_size).get("list") or []
    transfers: list[dict[str, Any]] = []
    try:
        transfers = client.transfer_history(page=1, page_size=20).get("list") or []
    except BinanceAPIError:
        transfers = []

    seen_orders = set(state.get("seen_orders") or [])
    seen_positions = set(state.get("seen_positions") or [])
    seen_transfers = set(state.get("seen_transfers") or [])
    bootstrap = bool(state.get("bootstrap", True))

    new_orders = [o for o in orders if order_key(o) not in seen_orders]
    new_positions = [p for p in positions if position_key(p) not in seen_positions]
    new_transfers = [t for t in transfers if transfer_key(t) not in seen_transfers]

    # API returns newest-first; alert oldest-first for chronological readability.
    new_orders = list(reversed(new_orders))
    new_positions = list(reversed(new_positions))
    new_transfers = list(reversed(new_transfers))

    if bootstrap:
        print(
            f"[{shanghai_now().strftime('%H:%M:%S')}] bootstrap "
            f"{name}: seed {len(orders)} orders / {len(positions)} closes "
            f"(no alerts on first run)"
        )
        print_detail(detail)
        print_orders(orders[:8], title="当前最新订单")
        print_positions(positions[:5], title="当前最新平仓")
    else:
        stamp = shanghai_now().strftime("%H:%M:%S")
        if not cfg.quiet:
            print(
                f"[{stamp}] poll ok  lastTrade={fmt_ts(detail.get('lastTradeTime'))}  "
                f"new_orders={len(new_orders)} new_closes={len(new_positions)}  "
                f"margin={fmt_num(detail.get('marginBalance'))}"
            )
        for order in new_orders:
            notify(cfg, format_order_alert(name, order))
        for pos in new_positions:
            notify(cfg, format_position_alert(name, pos))
        for item in new_transfers:
            notify(
                cfg,
                f"[{name}] 资金变动\n"
                f"时间: {fmt_ts(item.get('time') or item.get('createTime'))}\n"
                f"原始: {json.dumps(item, ensure_ascii=False)[:500]}",
            )

    for order in orders:
        seen_orders.add(order_key(order))
    for pos in positions:
        seen_positions.add(position_key(pos))
    for item in transfers:
        seen_transfers.add(transfer_key(item))

    state["seen_orders"] = trim_seen(sorted(seen_orders))
    state["seen_positions"] = trim_seen(sorted(seen_positions))
    state["seen_transfers"] = trim_seen(sorted(seen_transfers))
    state["bootstrap"] = False
    state["last_poll_at"] = shanghai_now().isoformat()
    state["portfolio_id"] = cfg.portfolio_id
    state["last_detail"] = {
        "nickname": detail.get("nickname"),
        "status": detail.get("status"),
        "positionShow": detail.get("positionShow"),
        "aumAmount": detail.get("aumAmount"),
        "marginBalance": detail.get("marginBalance"),
        "currentCopyCount": detail.get("currentCopyCount"),
        "maxCopyCount": detail.get("maxCopyCount"),
        "lastTradeTime": detail.get("lastTradeTime"),
        "copierPnl": detail.get("copierPnl"),
    }
    return state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="监控币安带单员「熬鹰资本」公开成交 / 平仓事件"
    )
    parser.add_argument(
        "--portfolio-id",
        default=os.environ.get("AOYING_PORTFOLIO_ID", DEFAULT_PORTFOLIO_ID),
        help=f"带单组合 ID（默认 {DEFAULT_PORTFOLIO_ID}）",
    )
    parser.add_argument(
        "--state",
        default=os.environ.get(
            "AOYING_STATE_PATH", "tools/aoying_monitor/state.json"
        ),
        help="去重状态文件路径",
    )
    parser.add_argument(
        "--webhook-url",
        default=os.environ.get("AOYING_WEBHOOK_URL"),
        help="可选：Slack/Discord/飞书/Telegram sendMessage webhook",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=50,
        help="每次拉取订单/仓位条数（默认 50）",
    )
    parser.add_argument(
        "--reconstruct-pages",
        type=int,
        default=5,
        help="敞口推算翻页数（默认 5）",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="减少常规轮询输出（仍打印告警）",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("once", help="拉一次快照并退出")

    watch = sub.add_parser("watch", help="持续轮询，发现新成交/平仓后告警")
    watch.add_argument(
        "--interval",
        type=float,
        default=float(os.environ.get("AOYING_INTERVAL", "15")),
        help="轮询间隔秒（默认 15，建议 >= 10）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = MonitorConfig(
        portfolio_id=str(args.portfolio_id),
        interval=float(getattr(args, "interval", 15.0)),
        page_size=max(5, min(int(args.page_size), 100)),
        state_path=Path(args.state),
        webhook_url=args.webhook_url,
        quiet=bool(args.quiet),
        reconstruct_pages=max(1, min(int(args.reconstruct_pages), 20)),
    )
    client = BinanceLeadClient(cfg.portfolio_id)

    if args.command == "once":
        snapshot(cfg, client)
        return 0

    # watch
    state = load_state(cfg.state_path)
    print(
        f"watching portfolio={cfg.portfolio_id} interval={cfg.interval}s "
        f"state={cfg.state_path}"
    )
    backoff = cfg.interval
    while True:
        try:
            state = poll_once(cfg, client, state)
            save_state(cfg.state_path, state)
            backoff = cfg.interval
        except BinanceAPIError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            backoff = min(max(backoff * 1.8, cfg.interval), 120.0)
            print(f"[backoff] sleep {backoff:.1f}s", file=sys.stderr)
        except KeyboardInterrupt:
            print("\nstopped")
            save_state(cfg.state_path, state)
            return 0
        time.sleep(backoff)


if __name__ == "__main__":
    raise SystemExit(main())
