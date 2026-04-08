# -*- coding: utf-8 -*-
# === swarm_sync.py ===

from optimizer_memory import load_optimizer_memory

# Load winrate-tuned parameters per coin-strategy
optimizer_data = load_optimizer_memory()

def swarm_decision(symbol, optimizer_data):
    decisions = []
    if symbol not in optimizer_data:
        return [], None, 0.0  # No decision

    for strategy, details in optimizer_data[symbol].items():
        confidence = details.get("winrate", 0)
        if confidence >= 91:
            decisions.append({
                "strategy": strategy,
                "confidence": confidence,
                "params": details.get("params", {})
            })

    if not decisions:
        return [], None, 0.0

    # Pick the best strategy
    best = max(decisions, key=lambda x: x["confidence"])
    return best["strategy"], "BUY", best["confidence"]
