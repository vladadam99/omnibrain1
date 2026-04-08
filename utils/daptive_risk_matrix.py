# -*- coding: utf-8 -*-
def compute_risk_settings(coin_data, volatility, drawdown_streak, confidence, base_amount=10):
    sl_multiplier = 1.2 if volatility > 0.05 else 0.8
    tp_multiplier = 2.5 if confidence > 90 else 1.5

    risk_scale = 1.0
    if drawdown_streak >= 3:
        risk_scale = 0.5
    elif confidence > 95:
        risk_scale = 2.0
    elif volatility < 0.01:
        risk_scale = 0.7

    trade_amount = base_amount * risk_scale
    return {
        'trade_amount': round(trade_amount, 2),
        'sl_multiplier': round(sl_multiplier, 2),
        'tp_multiplier': round(tp_multiplier, 2),
    }
