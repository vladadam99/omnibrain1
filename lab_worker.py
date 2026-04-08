# /root/omnibrain3/lab_worker.py
import json
import time
import redis

from app.persistence.database import SessionLocal
from app.models.entities import AgentVersion, Run, RunMetric  # from your Phase 5 project
from app.services.validation import ValidationService
from app.services.evolution import EvolutionService
from lab_adapters import run_futures_backtest, run_evolution_cycle_job

redis_client = redis.Redis.from_url("redis://localhost:6379/0")

def handle_backtest(job: dict):
    db = SessionLocal()
    try:
        av = db.query(AgentVersion).filter(AgentVersion.id == job["agent_version_id"]).first()
        if not av:
            return
        metrics = run_futures_backtest(
            symbol=job["symbol"],
            timeframe=job["timeframe"],
            start_ts_ms=job["start_ts_ms"],
            end_ts_ms=job["end_ts_ms"],
            agent_name=av.agent.name if hasattr(av, "agent") else "agent",
            agent_config=av.config,
        )
        run = Run(
            run_type="backtest",
            status="completed",
            symbol=job["symbol"],
            timeframe=job["timeframe"],
            config_snapshot=av.config,
        )
        db.add(run)
        db.flush()
        rm = RunMetric(
            run_id=run.id,
            agent_version_id=av.id,
            metrics=metrics,
            robustness_score=float(metrics.get("robustness_score", 0.0)),
        )
        db.add(rm)
        db.commit()
    finally:
        db.close()

def handle_evolution(job: dict):
    db = SessionLocal()
    try:
        summary = run_evolution_cycle_job(
            symbol=job["symbol"],
            timeframe=job["timeframe"],
            windows=job["windows"],
        )
        db.commit()
    finally:
        db.close()

def handle_validation(job: dict):
    db = SessionLocal()
    try:
        svc = ValidationService()
        svc.validate_metrics(
            db,
            agent_version_id=job["agent_version_id"],
            metrics=job["metrics"],
        )
    finally:
        db.close()

def main_loop():
    queues = ["queue:backtest", "queue:evolution", "queue:validation"]
    while True:
        q, raw = redis_client.blpop(queues, timeout=5) or (None, None)
        if not raw:
            continue
        try:
            job = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        t = job.get("type")
        if t == "backtest":
            handle_backtest(job)
        elif t == "evolution":
            handle_evolution(job)
        elif t == "validation":
            handle_validation(job)

if __name__ == "__main__":
    main_loop()
