from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from cta.config import load_config, load_env
from cta.engine import LiveEngine


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Trend CTA live trader for crypto USDT-M perpetuals")
    p.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parents[1] / "config.yaml"),
        help="Path to config.yaml",
    )
    p.add_argument("--once", action="store_true", help="Run a single evaluation pass and exit")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    env = load_env()

    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    engine = LiveEngine(cfg, env)
    if args.once:
        engine.bootstrap()
        for symbol in cfg.symbols:
            engine.on_bar(symbol)
        engine.status_table()
        return 0

    engine.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
