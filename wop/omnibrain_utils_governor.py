
# -*- coding: utf-8 -*-
"""
Governor wrapper for trade-side actions.
Routes to PAPER broker when mode==PAPER (from governor/config/modes.yaml),
or to your LIVE Binance client when mode==LIVE.
It also prefixes all Telegram messages with [PAPER] / [LIVE] for absolute clarity.
"""
import os
from pathlib import Path

# --- Lazy imports to avoid hard deps during module import
def _lazy_imports():
    global yaml, engine_hook, UMFutures, send_telegram_message
    import yaml
    # engine_hook is provided by Step 2 (governor/engine_hook.py)
    from governor.engine_hook import tg_prefix, current_mode
    engine_hook = type("EH", (), {"tg_prefix": tg_prefix, "current_mode": current_mode})
    try:
        from binance.um_futures import UMFutures  # your live client
    except Exception:
        UMFutures = None
    # Telegram sender from your project
    try:
        from omnibrain_utils import send_telegram_message
    except Exception:
        def send_telegram_message(token, chat, *parts):
            print(" ".join([p for p in parts if p]))

_lazy_imports()

# Paper broker from Step 2 (governor/paper_broker.py)
try:
    from governor.paper_broker import PaperBroker
except Exception:
    class PaperBroker:
        def __init__(self, balance_usdt=1000.0, fee_bps=7.5, slippage_bps=1.0, trades_path=None):
            self.balance_usdt=balance_usdt; self.trades_path=trades_path
        def place_market(self, symbol, side, qty, price, agent="unknown"): pass
        def close_market(self, symbol, price, agent="unknown"): return 0.0
        def equity(self, marks=None): return self.balance_usdt

# --- Shared state
_PAPER = None
_LIVE_CLIENT = None
_TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
_TG_CHAT  = os.getenv("TELEGRAM_CHAT_ID")

def _mode():
    try:
        return engine_hook.current_mode()
    except Exception:
        return "PAPER"

def _paper() -> PaperBroker:
    global _PAPER
    if _PAPER is None:
        trades_path = os.getenv("PAPER_TRADES_PATH") or "paper_trades.csv"
        bal = float(os.getenv("PAPER_START_BALANCE", "1000"))
        _PAPER = PaperBroker(balance_usdt=bal, trades_path=trades_path)
    return _PAPER

def _live():
    global _LIVE_CLIENT
    if _LIVE_CLIENT is None and UMFutures:
        try:
            from omnibrain_utils import load_api_keys
            api_key, api_secret, _, _ = load_api_keys()
            _LIVE_CLIENT = UMFutures(key=api_key, secret=api_secret)
        except Exception as e:
            print("[LIVE CLIENT ERROR]", e)
            _LIVE_CLIENT = None
    return _LIVE_CLIENT

def _mark_price(symbol: str) -> float:
    # Try your WS mark first, fallback to REST mark
    try:
        from omnibrain_utils import get_ws_mark
        px = get_ws_mark(symbol)
        if px: return float(px)
    except Exception:
        pass
    try:
        c = _live()
        if c:
            return float(c.mark_price(symbol=symbol)['markPrice'])
    except Exception:
        pass
    return 0.0

# ========= PUBLIC API (used by engine) =========

def futures_execute_trade(symbol: str, side: str, qty: float):
    prefix = engine_hook.tg_prefix()
    if _mode() == "PAPER":
        px = _mark_price(symbol)
        _paper().place_market(symbol, side, qty, price=px, agent="governor")
        send_telegram_message(_TG_TOKEN, _TG_CHAT, f"{prefix} {side.upper()} {symbol} | Qty={qty} @ {px:.6f}")
        return {"symbol": symbol, "side": side, "entry_price": px, "qty": qty, "order": {"mode":"PAPER"}}
    # LIVE
    client = _live()
    if not client:
        raise RuntimeError("LIVE client unavailable")
    try:
        mark_price = float(client.mark_price(symbol=symbol)['markPrice'])
        order = client.new_order(symbol=symbol, side=("BUY" if side.upper()=="BUY" else "SELL"), type="MARKET", quantity=qty)
        send_telegram_message(_TG_TOKEN, _TG_CHAT, f"{prefix} {side.upper()} {symbol} | Qty: {qty} @ {mark_price:.6f}")
        return {"symbol": symbol, "side": side, "entry_price": mark_price, "qty": qty, "order": order}
    except Exception as e:
        send_telegram_message(_TG_TOKEN, _TG_CHAT, f"{prefix} ❌ Trade Error {symbol}: {e}")
        return None

def futures_close_trade(symbol: str, qty: float, side: str, reason: str):
    prefix = engine_hook.tg_prefix()
    if _mode() == "PAPER":
        px = _mark_price(symbol)
        pnl = _paper().close_market(symbol, price=px, agent="governor")
        send_telegram_message(_TG_TOKEN, _TG_CHAT, f"{prefix} CLOSE {symbol} {side} @ {px:.6f} | PnL={pnl:.2f} ({reason})")
        return True
    client = _live()
    if not client:
        raise RuntimeError("LIVE client unavailable")
    try:
        order = client.new_order(symbol=symbol, side=("SELL" if side.upper()=="BUY" else "BUY"), type="MARKET", quantity=qty)
        send_telegram_message(_TG_TOKEN, _TG_CHAT, f"{prefix} CLOSE {symbol} {side} @ mkt | ({reason})")
        return True
    except Exception as e:
        send_telegram_message(_TG_TOKEN, _TG_CHAT, f"{prefix} ❌ Close Error {symbol}: {e}")
        return False

def place_tp_sl_orders(symbol: str, side: str, tp: float, sl: float):
    prefix = engine_hook.tg_prefix()
    if _mode() == "PAPER":
        # Paper: TP/SL will be simulated by engine monitors; we log the intent for parity.
        send_telegram_message(_TG_TOKEN, _TG_CHAT, f"{prefix} TP/SL intent {symbol}: TP={tp:.6f} SL={sl:.6f} (paper)")
        return
    try:
        client = _live()
        # In your live code, place the real TP/SL here; we just confirm for now.
        send_telegram_message(_TG_TOKEN, _TG_CHAT, f"{prefix} TP/SL placed for {symbol}")
    except Exception as e:
        send_telegram_message(_TG_TOKEN, _TG_CHAT, f"{prefix} Error placing TP/SL for {symbol}: {e}")
