from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd

from cta.indicators import enrich_ohlcv, last_valid


class Side(str, Enum):
    FLAT = "flat"
    LONG = "long"
    SHORT = "short"


class Action(str, Enum):
    HOLD = "hold"
    OPEN_LONG = "open_long"
    OPEN_SHORT = "open_short"
    CLOSE = "close"


@dataclass(frozen=True)
class Signal:
    action: Action
    side: Side
    reason: str
    stop_price: Optional[float] = None
    atr: Optional[float] = None
    entry_price: Optional[float] = None


@dataclass
class PositionState:
    side: Side = Side.FLAT
    entry_price: float = 0.0
    stop_price: float = 0.0
    qty: float = 0.0
    bars_since_stop: int = 999


class DonchianCTA:
    """Classic Donchian breakout trend CTA with ATR hard stop."""

    def __init__(
        self,
        *,
        donchian_entry: int = 20,
        donchian_exit: int = 10,
        atr_period: int = 14,
        atr_stop_mult: float = 2.0,
        cooldown_bars_after_stop: int = 1,
    ) -> None:
        self.donchian_entry = donchian_entry
        self.donchian_exit = donchian_exit
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self.cooldown_bars_after_stop = cooldown_bars_after_stop

    def prepare(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(ohlcv.columns)
        if missing:
            raise ValueError(f"ohlcv missing columns: {sorted(missing)}")
        return enrich_ohlcv(
            ohlcv,
            donchian_entry=self.donchian_entry,
            donchian_exit=self.donchian_exit,
            atr_period=self.atr_period,
        )

    def evaluate(self, ohlcv: pd.DataFrame, pos: PositionState) -> Signal:
        df = self.prepare(ohlcv)
        if len(df) < max(self.donchian_entry, self.donchian_exit, self.atr_period) + 2:
            return Signal(Action.HOLD, pos.side, "warming_up")

        row = df.iloc[-1]
        close = float(row["close"])
        atr_v = last_valid(row["atr"])
        entry_high = last_valid(row["entry_high"])
        entry_low = last_valid(row["entry_low"])
        exit_high = last_valid(row["exit_high"])
        exit_low = last_valid(row["exit_low"])

        if None in (atr_v, entry_high, entry_low, exit_high, exit_low):
            return Signal(Action.HOLD, pos.side, "indicator_nan")

        # Hard stop first.
        if pos.side == Side.LONG and close <= pos.stop_price:
            return Signal(Action.CLOSE, Side.FLAT, "atr_stop_long", stop_price=pos.stop_price, atr=atr_v)
        if pos.side == Side.SHORT and close >= pos.stop_price:
            return Signal(Action.CLOSE, Side.FLAT, "atr_stop_short", stop_price=pos.stop_price, atr=atr_v)

        # Channel exit.
        if pos.side == Side.LONG and close <= exit_low:
            return Signal(Action.CLOSE, Side.FLAT, "donchian_exit_long", atr=atr_v)
        if pos.side == Side.SHORT and close >= exit_high:
            return Signal(Action.CLOSE, Side.FLAT, "donchian_exit_short", atr=atr_v)

        # Entries only when flat and cooldown expired.
        if pos.side == Side.FLAT:
            if pos.bars_since_stop < self.cooldown_bars_after_stop:
                return Signal(Action.HOLD, Side.FLAT, "cooldown")
            if close > entry_high:
                stop = close - self.atr_stop_mult * atr_v
                return Signal(
                    Action.OPEN_LONG,
                    Side.LONG,
                    "donchian_breakout_long",
                    stop_price=stop,
                    atr=atr_v,
                    entry_price=close,
                )
            if close < entry_low:
                stop = close + self.atr_stop_mult * atr_v
                return Signal(
                    Action.OPEN_SHORT,
                    Side.SHORT,
                    "donchian_breakout_short",
                    stop_price=stop,
                    atr=atr_v,
                    entry_price=close,
                )

        return Signal(Action.HOLD, pos.side, "no_edge", atr=atr_v)
