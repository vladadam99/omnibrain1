# -*- coding: utf-8 -*-
def safe_fmt(val, fmt=".4f", null="None"):
    try:
        if val is None:
            return null
        return ("{:" + fmt + "}").format(val)
    except Exception:
        return null

def get_adaptive_trail_percent(roi, atr=None, entry_price=None):
    """
    Adaptive trail percent based on ROI and volatility.
    Looser for noisy markets, tighter when in strong profit.
    """
    if roi > 30:
        return 0.6
    elif roi > 10:
        return 0.9
    elif atr and entry_price:
        return min(2.5, max(0.6, (atr * 2 / entry_price) * 100))
    else:
        return 2.0  # default for uncertain conditions

def check_trailing_stop_v2(symbol, side, entry_price, mark_price, highest, lowest, trail_percent, atr=None, time_open_min=0, logger=print):
    """
    Advanced trailing stop for fast scalping. Uses ATR buffer and short delay.
    Returns (should_close, new_highest, new_lowest, reason)
    """
    reason = None
    buffer_multiplier = 1.0       # Smooths out volatility noise
    min_time_before_trigger = 1.0  # 60 seconds (in minutes)

    logger(f"[TSv2] {symbol} side={side} entry={safe_fmt(entry_price)} price={safe_fmt(mark_price)} high={safe_fmt(highest)} low={safe_fmt(lowest)} trail%={safe_fmt(trail_percent)} ATR={safe_fmt(atr)}")

    if time_open_min < min_time_before_trigger:
        logger(f"[TSv2] {symbol} too early for TS (<{min_time_before_trigger * 60:.0f}s). Holding.")
        return False, highest, lowest, None

    buffer = atr * buffer_multiplier if atr else 0

    if side == "BUY":
        if mark_price > highest:
            highest = mark_price
            logger(f"[TSv2] [BUY] New highest: {safe_fmt(highest)}")
        trail_trigger = highest * (1 - trail_percent / 100)
        if mark_price <= trail_trigger - buffer:
            reason = f"TS: Price fell {safe_fmt(trail_percent)}% + buffer from peak"
            logger(f"[TSv2] [BUY] TS TRIGGERED at {safe_fmt(mark_price)} (trigger={safe_fmt(trail_trigger)}, buffer={safe_fmt(buffer)})")
            return True, highest, lowest, reason

    elif side == "SELL":
        if mark_price < lowest:
            lowest = mark_price
            logger(f"[TSv2] [SELL] New lowest: {safe_fmt(lowest)}")
        trail_trigger = lowest * (1 + trail_percent / 100)
        if mark_price >= trail_trigger + buffer:
            reason = f"TS: Price rose {safe_fmt(trail_percent)}% + buffer from trough"
            logger(f"[TSv2] [SELL] TS TRIGGERED at {safe_fmt(mark_price)} (trigger={safe_fmt(trail_trigger)}, buffer={safe_fmt(buffer)})")
            return True, highest, lowest, reason

    return False, highest, lowest, None
