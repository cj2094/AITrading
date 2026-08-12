# Crypto CTA Perp

Trend **CTA** live trader for crypto **USDT-M perpetual** futures (Binance first).

Classic Donchian breakout + ATR risk sizing, with dry-run by default.

## Features

- **Donchian Channel** entry / exit (Turtle-style trend CTA)
- **ATR** stop distance and volatility position sizing
- **Binance USDT-M** via [ccxt](https://github.com/ccxt/ccxt)
- **Dry-run** mode (default) — no orders until you set `dry_run: false`
- Risk guards: max leverage, max positions, daily loss halt, cooldown after stop

## Quick start

```bash
cd crypto-cta-perp
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# edit config.yaml — keep dry_run: true first

cta-live --config config.yaml
# or
python -m cta.cli --config config.yaml
```

## Config

See `config.yaml`:

| Key | Meaning |
|-----|---------|
| `symbols` | Perp symbols, e.g. `BTC/USDT:USDT` |
| `timeframe` | Bar size, default `1h` |
| `donchian_entry` / `donchian_exit` | Channel lookbacks |
| `atr_period` / `atr_stop_mult` | Stop distance |
| `risk_per_trade` | Fraction of equity risked per entry |
| `leverage` | Exchange leverage |
| `dry_run` | `true` = paper / signal only |

## Env

```bash
BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_TESTNET=false   # set true to use Binance Futures testnet
```

## Strategy logic (summary)

1. Fetch OHLCV, compute Donchian high/low and ATR.
2. Flat → long if close breaks `N`-bar high; short if breaks `N`-bar low.
3. In position → exit on opposite `M`-bar channel; hard stop at `entry ± ATR * mult`.
4. Size = `(equity * risk_per_trade) / (ATR * stop_mult)` in contracts, capped by leverage / notional limits.

## Tests

```bash
pytest -q
```

## Disclaimer

Experimental software. Crypto perpetual trading can liquidate your account. Use dry-run / testnet first. No warranty of profit.

## Standalone GitHub repository

This folder is intentionally self-contained. To publish as its own repo:

```bash
# 1) Create empty repo on GitHub (no README), e.g. cj2094/crypto-cta-perp
# 2) Push this directory as the repository root:
cd crypto-cta-perp
git init
git add .
git commit -m "Initial commit: trend CTA for USDT-M perpetuals"
git branch -M main
git remote add origin git@github.com:<you>/crypto-cta-perp.git
git push -u origin main
```

> Note: Binance Futures REST may return HTTP 451 from some cloud regions. Run live/dry-run from a network where `fapi.binance.com` is reachable (or Futures testnet).
