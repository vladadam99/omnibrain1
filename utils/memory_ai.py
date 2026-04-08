# -*- coding: utf-8 -*-
# memory_ai.py — OMNIBRAIN Agent Performance Memory AI

import os
import csv
from datetime import datetime

class MemoryAI:
    def __init__(self, file_path="strategy_memory.csv"):
        self.file_path = file_path
        self.memory = {}
        self.load_memory()

    def load_memory(self):
        if not os.path.exists(self.file_path):
            return
        with open(self.file_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                agent = row["agent"]
                self.memory[agent] = {
                    "wins": int(row["wins"]),
                    "losses": int(row["losses"]),
                    "last_updated": row.get("last_updated", "")
                }

    def update_memory(self, agent, win):
        if agent not in self.memory:
            self.memory[agent] = {"wins": 0, "losses": 0, "last_updated": ""}

        if win:
            self.memory[agent]["wins"] += 1
        else:
            self.memory[agent]["losses"] += 1

        self.memory[agent]["last_updated"] = datetime.utcnow().isoformat()
        self.save_memory()

    def save_memory(self):
        with open(self.file_path, "w", newline="") as f:
            fieldnames = ["agent", "wins", "losses", "last_updated"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for agent, stats in self.memory.items():
                row = {"agent": agent, **stats}
                writer.writerow(row)

    def get_confidence(self, agent):
        stats = self.memory.get(agent, {"wins": 0, "losses": 0})
        total = stats["wins"] + stats["losses"]
        if total == 0:
            return 1.0
        win_rate = stats["wins"] / total
        return round(1.0 * (0.8 + 0.4 * win_rate), 2)

# === Example ===
if __name__ == "__main__":
    mem = MemoryAI()
    mem.update_memory("RSI_2", True)
    mem.update_memory("MACD_Cross", False)
    print("📊 Confidence RSI_2:", mem.get_confidence("RSI_2"))
