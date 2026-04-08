# -*- coding: utf-8 -*-
from strategy_agents import (
    CosmicMACDAgent,
    CosmicRSIAgent,
    CosmicVortexAgent,
    CosmicWarpPulseAgent,
    CosmicSuperTrendAgent,
    CosmicBollingerAgent,
    CosmicVolumeSpikeAgent,
    CosmicMomentumAgent,
    CosmicBreakoutAgent,
    # Add any more agents you add in the future here
)

def initialize_strategies():
    return [
        CosmicMACDAgent(),
        CosmicRSIAgent(),
        CosmicVortexAgent(),
        CosmicWarpPulseAgent(),
        CosmicSuperTrendAgent(),
        CosmicBollingerAgent(),
        CosmicVolumeSpikeAgent(),
        CosmicMomentumAgent(),
        CosmicBreakoutAgent(),
        # All agents instantiated here
    ]
