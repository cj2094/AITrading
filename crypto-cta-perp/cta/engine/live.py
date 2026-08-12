from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Dict

from rich.console import Console
from rich.table import Table

from cta.config import AppConfig, EnvSettings
from cta.exchange import BinancePerpExchange
from cta.risk import RiskLimits, RiskManager
from cta.strategy import Action, DonchianCTA, PositionState, Side

log = logging.getLogger("cta.engine")
console = Console()


class LiveEngine:
    def __init__(self, cfg: AppConfig, env: EnvSettings) -> None:
        self.cfg = cfg
        testnet = cfg.testnet or env.binance_testnet
        self.ex = BinancePerpExchange(
            api_key=env.binance_api_key,
            api_secret=env.binance_api_secret,
            testnet=testnet,
            dry_run=cfg.dry_run,
            default_leverage=cfg.leverage,
        )
        self.strategy = DonchianCTA(
            donchian_entry=cfg.donchian_entry,
            donchian_exit=cfg.donchian_exit,
            atr_period=cfg.atr_period,
            atr_stop_mult=cfg.atr_stop_mult,
            cooldown_bars_after_stop=cfg.cooldown_bars_after_stop,
        )
        self.risk = RiskManager(
            RiskLimits(
                leverage=cfg.leverage,
                risk_per_trade=cfg.risk_per_trade,
                max_positions=cfg.max_positions,
                max_notional_pct=cfg.max_notional_pct,
                max_daily_loss_pct=cfg.max_daily_loss_pct,
            )
        )
        self.positions: Dict[str, PositionState] = {s: PositionState() for s in cfg.symbols}
        self._last_day: str | None = None
        self._bar_seen: Dict[str, object] = {}

    def bootstrap(self) -> None:
        mode = "DRY-RUN" if self.cfg.dry_run else "LIVE"
        console.print(f"[bold]crypto-cta-perp[/bold] starting in [cyan]{mode}[/cyan]")
        markets = self.ex.load_markets()
        if not markets and self.cfg.dry_run:
            console.print(
                "[yellow]Warning:[/yellow] exchange markets unavailable "
                "(geo-restriction or network). Dry-run continues with mock equity only."
            )
        for sym in self.cfg.symbols:
            try:
                self.ex.ensure_leverage(sym, self.cfg.leverage)
            except Exception as exc:
                if not self.cfg.dry_run:
                    raise
                log.warning("skip leverage for %s in dry-run: %s", sym, exc)
        try:
            equity = self.ex.fetch_balance_usdt()
        except Exception:
            if not self.cfg.dry_run:
                raise
            equity = 10_000.0
            console.print("[yellow]Using mock equity 10000 USDT (exchange unreachable)[/yellow]")
        self.risk.reset_day(equity)
        self._last_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        console.print(f"Equity: {equity:.2f} USDT | symbols={self.cfg.symbols}")

    def _roll_day(self, equity: float) -> None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_day != day:
            self.risk.reset_day(equity)
            self._last_day = day

    def _open_count(self) -> int:
        return sum(1 for p in self.positions.values() if p.side != Side.FLAT)

    def _sync_position_from_exchange(self, symbol: str) -> None:
        if self.cfg.dry_run:
            return
        remote = self.ex.fetch_position(symbol)
        local = self.positions[symbol]
        side = remote.get("side", "flat")
        if side in ("long", "short") and float(remote.get("contracts") or 0) > 0:
            local.side = Side.LONG if side == "long" else Side.SHORT
            local.qty = float(remote["contracts"])
            local.entry_price = float(remote.get("entryPrice") or local.entry_price)
        else:
            if local.side != Side.FLAT:
                local.side = Side.FLAT
                local.qty = 0.0

    def on_bar(self, symbol: str) -> None:
        try:
            ohlcv = self.ex.fetch_ohlcv(symbol, self.cfg.timeframe, self.cfg.candle_limit)
        except Exception as exc:
            log.warning("fetch_ohlcv failed for %s: %s", symbol, exc)
            return
        if ohlcv.empty:
            return
        ts = ohlcv.iloc[-1]["timestamp"]
        # Act once per closed-ish bar key; using last timestamp is fine for poll loop.
        if self._bar_seen.get(symbol) == ts:
            # Still allow stop checks intra-bar via last close.
            pass
        self._bar_seen[symbol] = ts

        pos = self.positions[symbol]
        signal = self.strategy.evaluate(ohlcv, pos)
        price = float(ohlcv.iloc[-1]["close"])
        equity = self.ex.fetch_balance_usdt()
        self._roll_day(equity)
        self.risk.update_equity(equity)

        log.info("%s signal=%s reason=%s side=%s price=%.4f", symbol, signal.action.value, signal.reason, pos.side.value, price)

        if signal.action == Action.CLOSE and pos.side != Side.FLAT:
            side = "sell" if pos.side == Side.LONG else "buy"
            order = self.ex.create_market_order(symbol, side, pos.qty, reduce_only=True)
            console.print(f"[yellow]CLOSE[/yellow] {symbol} {pos.side.value} qty={pos.qty} :: {signal.reason} :: {order.id}")
            stopped = signal.reason.startswith("atr_stop")
            pos.side = Side.FLAT
            pos.qty = 0.0
            pos.stop_price = 0.0
            pos.bars_since_stop = 0 if stopped else pos.bars_since_stop
            return

        if signal.action in (Action.OPEN_LONG, Action.OPEN_SHORT) and pos.side == Side.FLAT:
            ok, why = self.risk.can_open(self._open_count())
            if not ok:
                log.warning("skip entry %s: %s", symbol, why)
                return
            atr_v = signal.atr or 0.0
            sized = self.risk.position_size(
                equity=equity,
                price=price,
                atr=atr_v,
                atr_stop_mult=self.cfg.atr_stop_mult,
            )
            qty = self.ex.amount_to_precision(symbol, sized.qty)
            if qty <= 0:
                log.warning("skip entry %s: qty=0 (%s)", symbol, sized.reason)
                return
            side = "buy" if signal.action == Action.OPEN_LONG else "sell"
            order = self.ex.create_market_order(symbol, side, qty, reduce_only=False)
            pos.side = Side.LONG if signal.action == Action.OPEN_LONG else Side.SHORT
            pos.entry_price = signal.entry_price or price
            pos.stop_price = signal.stop_price or 0.0
            pos.qty = qty
            pos.bars_since_stop = 999
            console.print(
                f"[green]OPEN[/green] {symbol} {pos.side.value} qty={qty} "
                f"stop={pos.stop_price:.4f} :: {signal.reason} :: {order.id} ({sized.reason})"
            )
            return

        # Advance cooldown when flat and we observed a bar.
        if pos.side == Side.FLAT and pos.bars_since_stop < 999:
            pos.bars_since_stop += 1

    def status_table(self) -> None:
        table = Table(title="CTA Positions")
        table.add_column("Symbol")
        table.add_column("Side")
        table.add_column("Qty")
        table.add_column("Entry")
        table.add_column("Stop")
        for sym, pos in self.positions.items():
            table.add_row(
                sym,
                pos.side.value,
                f"{pos.qty}",
                f"{pos.entry_price:.4f}" if pos.entry_price else "-",
                f"{pos.stop_price:.4f}" if pos.stop_price else "-",
            )
        console.print(table)

    def run_forever(self) -> None:
        self.bootstrap()
        while True:
            for symbol in self.cfg.symbols:
                try:
                    self._sync_position_from_exchange(symbol)
                    self.on_bar(symbol)
                except Exception:
                    log.exception("error processing %s", symbol)
            self.status_table()
            time.sleep(self.cfg.poll_seconds)
