from pathlib import Path

from cta.config import load_config


def test_load_default_config():
    cfg = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    assert cfg.dry_run is True
    assert cfg.donchian_entry == 20
    assert "BTC/USDT:USDT" in cfg.symbols
