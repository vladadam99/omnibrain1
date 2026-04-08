# -*- coding: utf-8 -*-
def get_position_size(balance, confidence, volatility_score):
    base = balance * 0.1
    scale = confidence * volatility_score
    return round(base * scale, 2)

def adjust_sl_tp(entry_price, atr):
    stop_loss = entry_price - (1.2 * atr)
    take_profit = entry_price + (2.5 * atr)
    return round(stop_loss, 4), round(take_profit, 4)
