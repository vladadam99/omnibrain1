# -*- coding: utf-8 -*-
def fractal_flux_strategy(market_data):
    return (
        0.03 < market_data["volatility"] < 0.06 and
        -0.5 < market_data["price_change"] < 0.5
    )
