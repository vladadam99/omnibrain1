# /root/omnibrain3/lab_adapters.py
from typing import Dict, Any, List
from datetime import datetime
from omnibrainutils import loadopenpositions, getfuturesbalance  # adjust if needed
# import your existing engine modules here (signal loop, backtest helper, etc.)

def run_futures_backtest(
    symbol: str,
    timeframe: str,
    start_ts_ms: int,
    end_ts_ms: int,
    agent_name: str,
    agent_config: Dict[str, Any],
    initial_equity_usdt: float = 10_000.0,
) -> Dict[str, Any]:
    """
    TODO: wire this into your real backtest path.
    """
    # example stub shape; replace with real call:
    metrics = {
        "net_pnl": 0.0,
        "ending_equity": initial_equity_usdt,
        "max_drawdown": 0.0,
        "sharpe": 0.0,
        "sortino": 0.0,
        "win_rate": 0.0,
        "profit_factor": 1.0,
        "holdout_score": 0.0,
        "sensitivity_score": 0.0,
        "robustness_score": 0.0,
        "total_trades": 0,
        "liquidation_events": 0,
        "funding_pnl": 0.0,
        "trade_log": [],
    }
    return metrics

def run_futures_backtest_batch(
    jobs: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    return [
        run_futures_backtest(
            j["symbol"],
            j["timeframe"],
            j["start_ts_ms"],
            j["end_ts_ms"],
            j["agent_name"],
            j["agent_config"],
            j.get("initial_equity_usdt", 10_000.0),
        )
        for j in jobs
    ]

def run_evolution_cycle_job(
    symbol: str,
    timeframe: str,
    windows: List[Dict[str, int]],
) -> Dict[str, Any]:
    """
    TODO: orchestrate survivor selection + mutations + backtests.
    """
    return {
        "created_versions": [],
        "evaluated_versions": [],
        "promoted_versions": [],
    }

def get_live_status() -> Dict[str, Any]:
    """
    Wrap your existing live status utilities.
    """
    positions = loadopenpositions()  # your current dict
    equity, avail = getfuturesbalance()
    open_list = []
    for sym, pos in positions.items():
        open_list.append({
            "symbol": sym,
            "side": pos.get("side", "?"),
            "qty": float(pos.get("qty", 0) or 0),
            "entry_price": float(pos.get("entryprice", 0) or 0),
            "mark_price": float(pos.get("mark", pos.get("entryprice", 0)) or 0),
            "unrealized_pnl": float(pos.get("upnl", 0) or 0),
            "agent": pos.get("agent", "?"),
            "time_open_iso": pos.get("time", datetime.utcnow().isoformat()),
        })
    return {
        "equity_usdt": float(equity),
        "available_usdt": float(avail),
        "margin_in_use_usdt": float(equity - avail),
        "daily_realized_pnl": 0.0,  # can be wired from your daily stats
        "daily_trade_count": 0,
        "open_positions": open_list,
    }
