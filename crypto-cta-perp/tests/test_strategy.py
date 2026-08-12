from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cta.risk import RiskLimits, RiskManager
from cta.strategy import Action, DonchianCTA, PositionState, Side


def _trend_df(n: int = 80, breakout: bool = True) -> pd.DataFrame:
    # Mild uptrend then optional breakout bar.
    rng = np.random.default_rng(42)
    close = 100 + np.linspace(0, 5, n) + rng.normal(0, 0.1, n)
    if breakout:
        close[-1] = close[-2] + 10  # clear breakout
    high = close + 0.5
    low = close - 0.5
    open_ = close.copy()
    vol = np.full(n, 1000.0)
    ts = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {"timestamp": ts, "open": open_, "high": high, "low": low, "close": close, "volume": vol}
    )


def test_donchian_long_breakout():
    strat = DonchianCTA(donchian_entry=20, donchian_exit=10, atr_period=14, atr_stop_mult=2.0)
    sig = strat.evaluate(_trend_df(breakout=True), PositionState())
    assert sig.action == Action.OPEN_LONG
    assert sig.side == Side.LONG
    assert sig.stop_price is not None and sig.stop_price < sig.entry_price


def test_donchian_hold_when_no_breakout():
    strat = DonchianCTA(donchian_entry=20, donchian_exit=10, atr_period=14)
    sig = strat.evaluate(_trend_df(breakout=False), PositionState())
    assert sig.action == Action.HOLD


def test_atr_stop_closes_long():
    strat = DonchianCTA(donchian_entry=20, donchian_exit=10, atr_period=14, atr_stop_mult=2.0)
    df = _trend_df(breakout=False)
    pos = PositionState(side=Side.LONG, entry_price=120.0, stop_price=200.0, qty=1.0)
    # Force close below stop
    df.loc[df.index[-1], "close"] = 150.0
    df.loc[df.index[-1], "high"] = 151.0
    df.loc[df.index[-1], "low"] = 149.0
    sig = strat.evaluate(df, pos)
    assert sig.action == Action.CLOSE
    assert sig.reason == "atr_stop_long"


def test_risk_sizing_and_halt():
    rm = RiskManager(RiskLimits(leverage=3, risk_per_trade=0.01, max_notional_pct=0.5, max_daily_loss_pct=0.03))
    sized = rm.position_size(equity=10_000, price=100, atr=2.0, atr_stop_mult=2.0)
    assert sized.qty > 0
    # stop distance = 4, risk cash = 100 => qty = 25
    assert sized.qty == pytest.approx(25.0)

    rm.reset_day(10_000)
    rm.update_equity(9_600)  # -4%
    ok, reason = rm.can_open(0)
    assert not ok
    assert "daily_loss" in reason
