# -*- coding: utf-8 -*-
# --- config_loader.py ---
import yaml
import os

def load_config():
    path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError("config.yaml not found.")
    
    with open(path, "r") as f:
        cfg = yaml.safe_load(f)

    # Sanity defaults if not present
    cfg.setdefault("mode", "backtest")
    cfg.setdefault("symbol", "BTCUSDT")
    cfg.setdefault("interval", "1h")
    cfg.setdefault("binance", {})
    cfg["binance"].setdefault("api_key", "")
    cfg["binance"].setdefault("api_secret", "")
    cfg["binance"].setdefault("trade_qty", 0.001)
    cfg.setdefault("agents", {})

    return cfg
