from __future__ import annotations

import numpy as np
import pandas as pd


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def donchian_high(high: pd.Series, period: int) -> pd.Series:
    # Exclude current bar so a close breakout is meaningful.
    return high.shift(1).rolling(period, min_periods=period).max()


def donchian_low(low: pd.Series, period: int) -> pd.Series:
    return low.shift(1).rolling(period, min_periods=period).min()


def enrich_ohlcv(
    df: pd.DataFrame,
    *,
    donchian_entry: int,
    donchian_exit: int,
    atr_period: int,
) -> pd.DataFrame:
    out = df.copy()
    out["entry_high"] = donchian_high(out["high"], donchian_entry)
    out["entry_low"] = donchian_low(out["low"], donchian_entry)
    out["exit_high"] = donchian_high(out["high"], donchian_exit)
    out["exit_low"] = donchian_low(out["low"], donchian_exit)
    out["atr"] = atr(out["high"], out["low"], out["close"], atr_period)
    return out


def last_valid(row_value: float | np.floating | None) -> float | None:
    if row_value is None or (isinstance(row_value, float) and np.isnan(row_value)):
        return None
    return float(row_value)
