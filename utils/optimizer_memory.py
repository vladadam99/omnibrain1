# -*- coding: utf-8 -*-
import json
import os

OPTIMIZER_MEMORY_PATH = "optimizer_memory.json"

def load_optimizer_memory():
    if os.path.exists(OPTIMIZER_MEMORY_PATH):
        with open(OPTIMIZER_MEMORY_PATH, "r") as f:
            return json.load(f)
    else:
        return {}

def save_optimizer_memory(data):
    with open(OPTIMIZER_MEMORY_PATH, "w") as f:
        json.dump(data, f, indent=2)
