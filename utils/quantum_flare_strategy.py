# -*- coding: utf-8 -*-
def quantum_flare_strategy(market_data, sentiment):
    return (
        market_data["volatility"] > 0.07 and
        market_data["price_change"] > 1.2 and
        sentiment > 0.65
    )
