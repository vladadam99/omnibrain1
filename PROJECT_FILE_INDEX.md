# OMNIBRAIN Project File Index (snapshot-based)
_Generated: 2026-05-29 01:06:59Z (UTC)_

This index was generated from the provided `Omnibrain1-main.zip` snapshot. It summarizes the repo structure and highlights the files involved in the **live futures bot**.

## Top-level overview
- Total files: **2791**
- Python files: **136**

| Path | Files | Notes |
|---|---:|---|
| `.bt_cache` | 1704 | Cache artifacts (safe to delete, should be gitignored) |
| `node_modules` | 501 | NPM deps (reinstallable; should not be committed) |
| `bob_runs` | 235 | Optimization runs/artifacts (optional; can be archived elsewhere) |
| `backtests` | 108 | Backtest outputs (optional; can be regenerated) |
| `utils` | 54 | Not referenced by the live futures engine in this snapshot |
| `wop` | 27 | Separate framework; not referenced by the live futures engine in this snapshot |
| `agents` | 14 | APEX agents used by the futures engine |
| `data` | 13 | State/memory files |
| `templates` | 7 | Template configs |
| `app` | 5 | Python/Flask demo UI (not used by the futures engine) |
| `bob_runs.FROZEN_20251007_005307` | 4 | Archived run snapshot |

## Core runtime for the Futures bot (what the engine actually needs)
The live engine is `auto_trade_futures.py`. In this snapshot it directly depends on:

- `auto_trade_futures.py`
- `safe_fetch_helper.py`
- `fingerprint_engine.py`
- `omnibrain_utils.py`
- `agents/` (APEX agents)
- `open_positions.json` (persistent position state)
- `agent_stats.pkl` (agent stats/threshold memory)
- `fingerprints_wins.jsonl` / `fingerprints_losses.jsonl` (fingerprint memory)

## Small directories (fully listed)

### `agents/`
- `agents/__init__.py`
- `agents/apex_config.py`
- `agents/apex_microburst.py`
- `agents/apex_momentum_pump.py`
- `agents/apex_supertrend_adaptive.py`
- `agents/apex_sweep_reversal.py`
- `agents/apex_vwap_pullback.py`
- `agents/dynamic_loader.py`

### `templates/`
- `templates/agent_config.json`
- `templates/bot_config.json`
- `templates/defaults.json`
- `templates/symbols.json`
- `templates/tf_defaults.json`
- `templates/trade_template.json`
- `templates/wallet.json`

### `tools/`
- `tools/apply_run.py`

### `app/` (Python/Flask demo)
- `app/__init__.py`
- `app/views.py`
- `app/swarm.py`
- `app/static/main.js`
- `app/templates/index.html`

## Sensitive files (do not keep in public repos)
The snapshot contains filenames that typically hold secrets:
- `.bob_env`
- `.govbot.env`
- `REAL.json`
- `REALBOB.json`
- `TELEGRAM.TXT`

## Notes about mismatches / likely outdated scripts in this snapshot
Some launcher scripts reference files/folders that are **not present** in this snapshot:
- `start_omnibrain.bat` references `auto_trade.py` and a `frontend/` folder (not present).
- `run_bob_default.sh` / `progress_bob.sh` reference `BOB_ASI_Pro_Plus.py` (not present; closest is `BOB_ASI_Pro_Plus_SANDBOX_UPG.py`).
- `start_all_screen.sh` references `/root/omnibrain2` and `governor/*` + `bob.py` (not present in this snapshot).

If you want, we can normalize the repo so launch scripts match the actual files present.
