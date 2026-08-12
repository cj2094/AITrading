from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import ccxt
import pandas as pd


@dataclass
class OrderResult:
    id: str
    symbol: str
    side: str
    amount: float
    price: Optional[float]
    status: str
    raw: dict[str, Any]
    dry_run: bool = False


class BinancePerpExchange:
    """Thin ccxt wrapper for Binance USDT-M perpetual."""

    def __init__(
        self,
        *,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = False,
        dry_run: bool = True,
        default_leverage: int = 3,
    ) -> None:
        self.dry_run = dry_run
        self.default_leverage = default_leverage
        self._leverage_set: set[str] = set()

        options: dict[str, Any] = {"defaultType": "swap"}
        if testnet:
            options["sandboxMode"] = True

        self.client = ccxt.binanceusdm(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "options": options,
            }
        )
        if testnet:
            self.client.set_sandbox_mode(True)

    def load_markets(self) -> dict[str, Any]:
        try:
            return self.client.load_markets()
        except Exception:
            if self.dry_run:
                # Geo-blocked / offline dry-run: allow local signal loop with empty markets.
                return {}
            raise

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        rows = self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df

    def fetch_balance_usdt(self) -> float:
        if self.dry_run and not self.client.apiKey:
            return 10_000.0
        bal = self.client.fetch_balance()
        total = bal.get("USDT", {}).get("total")
        if total is None:
            # Some responses nest under info / free
            free = bal.get("USDT", {}).get("free")
            return float(free or 0.0)
        return float(total)

    def fetch_position(self, symbol: str) -> dict[str, Any]:
        if self.dry_run and not self.client.apiKey:
            return {"symbol": symbol, "side": "flat", "contracts": 0.0, "entryPrice": 0.0}
        positions = self.client.fetch_positions([symbol])
        for p in positions:
            contracts = float(p.get("contracts") or 0.0)
            if abs(contracts) > 0:
                side = p.get("side") or ("long" if contracts > 0 else "short")
                return {
                    "symbol": symbol,
                    "side": side,
                    "contracts": abs(contracts),
                    "entryPrice": float(p.get("entryPrice") or 0.0),
                    "raw": p,
                }
        return {"symbol": symbol, "side": "flat", "contracts": 0.0, "entryPrice": 0.0}

    def ensure_leverage(self, symbol: str, leverage: int | None = None) -> None:
        lev = leverage or self.default_leverage
        if symbol in self._leverage_set:
            return
        if self.dry_run and not self.client.apiKey:
            self._leverage_set.add(symbol)
            return
        self.client.set_leverage(lev, symbol)
        try:
            self.client.set_margin_mode("cross", symbol)
        except Exception:
            # Already in desired mode or unsupported — ignore.
            pass
        self._leverage_set.add(symbol)

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        try:
            return float(self.client.amount_to_precision(symbol, amount))
        except Exception:
            return float(f"{amount:.6f}")

    def create_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        *,
        reduce_only: bool = False,
    ) -> OrderResult:
        amount = self.amount_to_precision(symbol, amount)
        if amount <= 0:
            raise ValueError("order amount must be > 0")

        params: dict[str, Any] = {}
        if reduce_only:
            params["reduceOnly"] = True

        if self.dry_run:
            return OrderResult(
                id=f"dry-{symbol}-{side}-{amount}",
                symbol=symbol,
                side=side,
                amount=amount,
                price=None,
                status="dry_run",
                raw={"params": params},
                dry_run=True,
            )

        order = self.client.create_order(symbol, "market", side, amount, params=params)
        return OrderResult(
            id=str(order.get("id")),
            symbol=symbol,
            side=side,
            amount=float(order.get("amount") or amount),
            price=(float(order["average"]) if order.get("average") is not None else None),
            status=str(order.get("status") or "unknown"),
            raw=order,
            dry_run=False,
        )
