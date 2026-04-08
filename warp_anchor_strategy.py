# -*- coding: utf-8 -*-
def warp_anchor_strategy(market_data):
    return (
        market_data["volatility"] < 0.04 and
        abs(market_data["price_change"]) > 1.5
    )
