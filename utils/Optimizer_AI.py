# -*- coding: utf-8 -*-
import logging
import random
from typing import List
from strategy_agents import BaseAgent

logger = logging.getLogger("OMNIBRAIN")

class OptimizerAI:
    def __init__(self, strategies: List[BaseAgent]):
        self.strategies = strategies
        self.performance_memory = {agent.name: [] for agent in strategies}

    def record_performance(self, agent_name: str, profit: float):
        if agent_name in self.performance_memory:
            self.performance_memory[agent_name].append(profit)
            if len(self.performance_memory[agent_name]) > 100:
                self.performance_memory[agent_name].pop(0)

    def get_average_performance(self, agent_name: str) -> float:
        history = self.performance_memory.get(agent_name, [])
        if not history:
            return 0.0
        return sum(history) / len(history)

    def choose_best_agents(self) -> List[BaseAgent]:
        """Return top agents by avg performance."""
        ranked = sorted(
            self.strategies,
            key=lambda ag: self.get_average_performance(ag.name),
            reverse=True
        )
        top_count = max(1, len(ranked) // 3)  # Top third
        return ranked[:top_count]

    def tune_parameters(self):
        """Simple genetic algorithm style parameter tuning."""
        for agent in self.strategies:
            # Random small adjustments
            for param in agent.tunable_params():
                current_val = getattr(agent, param)
                change = random.uniform(-0.1, 0.1) * current_val
                new_val = max(current_val + change, 0.0001)  # prevent zero or negative
                setattr(agent, param, new_val)
            logger.info(f"Tuned parameters for {agent.name}")

    def run_evolution_cycle(self):
        """Call periodically to improve agent parameters."""
        self.tune_parameters()
        logger.info("OptimizerAI evolution cycle completed.")
