
# -*- coding: utf-8 -*-
"""
Tiny client to interact with the Governor API from scripts:
- propose (register candidate)
- start paper
- stop paper
- promote
"""
import requests, time
from pathlib import Path

API = "http://127.0.0.1:8088"

def propose(run_id: str, trial_id: str) -> str:
    r = requests.post(API+"/governor/propose", json={"bob_run_id": run_id, "trial_id": trial_id}, timeout=10)
    r.raise_for_status()
    return r.json()["candidate_id"]

def start_paper(candidate_id: str, days: int = 2):
    r = requests.post(API+"/governor/paper/start", json={"candidate_id": candidate_id, "days": days}, timeout=10)
    r.raise_for_status()
    return r.json()

def stop_paper(candidate_id: str):
    r = requests.post(API+"/governor/paper/stop", json={"candidate_id": candidate_id}, timeout=10)
    r.raise_for_status()
    return r.json()

def promote(candidate_id: str, force: bool = False):
    r = requests.post(API+"/governor/promote", json={"candidate_id": candidate_id, "force": force}, timeout=10)
    r.raise_for_status()
    return r.json()
