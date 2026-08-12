from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseModel):
    exchange: Literal["binanceusdm"] = "binanceusdm"
    testnet: bool = False
    dry_run: bool = True
    symbols: list[str] = Field(default_factory=lambda: ["BTC/USDT:USDT"])
    timeframe: str = "1h"
    poll_seconds: int = 30
    candle_limit: int = 200
    donchian_entry: int = 20
    donchian_exit: int = 10
    atr_period: int = 14
    atr_stop_mult: float = 2.0
    leverage: int = 3
    risk_per_trade: float = 0.01
    max_positions: int = 2
    max_notional_pct: float = 0.5
    max_daily_loss_pct: float = 0.03
    cooldown_bars_after_stop: int = 1
    log_level: str = "INFO"

    @field_validator("symbols")
    @classmethod
    def non_empty_symbols(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("symbols must not be empty")
        return v

    @field_validator("donchian_entry", "donchian_exit", "atr_period")
    @classmethod
    def positive_lookbacks(cls, v: int) -> int:
        if v < 2:
            raise ValueError("lookback periods must be >= 2")
        return v


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = False


def load_config(path: str | Path) -> AppConfig:
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(raw)


@lru_cache(maxsize=1)
def load_env() -> EnvSettings:
    return EnvSettings()
