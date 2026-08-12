from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskLimits:
    leverage: int = 3
    risk_per_trade: float = 0.01
    max_positions: int = 2
    max_notional_pct: float = 0.5
    max_daily_loss_pct: float = 0.03


@dataclass
class SizeResult:
    qty: float
    notional: float
    stop_distance: float
    capped: bool
    reason: str


class RiskManager:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits
        self.day_start_equity: float | None = None
        self.halted: bool = False
        self.halt_reason: str = ""

    def reset_day(self, equity: float) -> None:
        self.day_start_equity = equity
        self.halted = False
        self.halt_reason = ""

    def update_equity(self, equity: float) -> None:
        if self.day_start_equity is None:
            self.reset_day(equity)
            return
        if self.day_start_equity <= 0:
            return
        dd = (equity - self.day_start_equity) / self.day_start_equity
        if dd <= -abs(self.limits.max_daily_loss_pct):
            self.halted = True
            self.halt_reason = f"daily_loss_{dd:.2%}"

    def can_open(self, open_positions: int) -> tuple[bool, str]:
        if self.halted:
            return False, self.halt_reason or "halted"
        if open_positions >= self.limits.max_positions:
            return False, "max_positions"
        return True, "ok"

    def position_size(
        self,
        *,
        equity: float,
        price: float,
        atr: float,
        atr_stop_mult: float,
        contract_size: float = 1.0,
    ) -> SizeResult:
        if equity <= 0 or price <= 0 or atr <= 0:
            return SizeResult(0.0, 0.0, 0.0, True, "invalid_inputs")

        stop_distance = atr * atr_stop_mult
        if stop_distance <= 0:
            return SizeResult(0.0, 0.0, stop_distance, True, "zero_stop")

        risk_cash = equity * self.limits.risk_per_trade
        raw_qty = risk_cash / (stop_distance * contract_size)

        max_notional = equity * self.limits.max_notional_pct * self.limits.leverage
        max_qty_by_notional = max_notional / (price * contract_size)

        qty = min(raw_qty, max_qty_by_notional)
        capped = qty < raw_qty - 1e-12
        notional = qty * price * contract_size
        reason = "capped_notional" if capped else "risk_sized"
        return SizeResult(qty=qty, notional=notional, stop_distance=stop_distance, capped=capped, reason=reason)
