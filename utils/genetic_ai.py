# -*- coding: utf-8 -*-
import json
import random
from optimizer_memory import save_optimizer_memory, load_optimizer_memory

def mutate_strategy(params):
    mutated = params.copy()
    for key in mutated:
        if isinstance(mutated[key], (int, float)):
            change = random.choice([-1, 1]) * random.uniform(0.05, 0.2) * mutated[key]
            mutated[key] += change
            if isinstance(params[key], int):
                mutated[key] = max(1, int(mutated[key]))
            else:
                mutated[key] = round(mutated[key], 2)
    return mutated

def evolve_strategies(memory_file='optimizer_memory.json'):
    memory = load_optimizer_memory(memory_file)
    evolved = {}
    for key, data in memory.items():
        old_params = data.get('params', {})
        winrate = data.get('winrate', 50)
        new_params = mutate_strategy(old_params)
        evolved[key] = {'params': new_params, 'winrate': round(winrate + random.uniform(-2, 3), 2)}
    save_optimizer_memory(evolved, memory_file)
    return evolved
