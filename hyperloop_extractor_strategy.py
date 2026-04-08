# -*- coding: utf-8 -*-
def hyperloop_extractor_strategy(market_data):
    return (
        market_data["volume"] > 2000000 and
        market_data["volatility"] > 0.09
    )
