# Cleanup Candidates (snapshot-based)
_Generated: 2026-05-29 (UTC)_

This file is based on a full read of `Omnibrain1-main.zip` (the snapshot you uploaded). It lists what appears **truly unused by the live futures engine** and/or **safe-to-delete build artifacts**, plus items that look **broken/outdated**.

## How the bot works (high-level)
The live trading engine in this snapshot is **`auto_trade_futures.py`**.

Core flow:
1. **Market data**
   - Websocket mark-price stream (`!markPrice@arr`) for fast pricing.
   - REST fallback in some paths.
   - 5m OHLCV pulls (`fetch_ohlcv`) for strategy signals.
   - 24h tickers via `safe_fetch_helper.safe_fetch_24h_tickers`.

2. **Signal generation & voting**
   - Loads APEX agents from `agents/` (vwap_pullback, sweep_reversal, microburst, plus optional supertrend_adaptive & momentum_pump).
   - Builds per-agent signals, weights them, and chooses a side.

3. **Risk, entry, state**
   - Computes SL/TP (baseline ATR + RR or agent hints depending on config).
   - Sizes qty based on margin/leverage constraints.
   - Sends a market order via `omnibrain_utils.futures_execute_trade`.
   - Persists state in `open_positions.json` and updates `agent_stats.pkl`.

4. **Exits**
   - Software TP/management thread (`quick_profit_monitor`) + SL/trailing enforcement in the monitor.
   - Fingerprint engine is used to **veto** bad setups and **record** outcomes (`fingerprints_*.jsonl`).

## Files the live engine directly depends on
- `auto_trade_futures.py`
- `safe_fetch_helper.py`
- `fingerprint_engine.py`
- `omnibrain_utils.py`
- `agents/` (APEX agent modules)
- `open_positions.json`
- `agent_stats.pkl`
- `fingerprints_wins.jsonl`
- `fingerprints_losses.jsonl`

Everything else below is evaluated relative to that.

---

## A) Safe-to-delete artifacts (HIGH confidence)
These are bulky, regenerable, and not required to run the engine.

### 1) `.bt_cache/`
- Reason: cache artifacts, not imported by runtime.
- Action: delete folder, add to `.gitignore`.

### 2) `node_modules/`
- Reason: reinstallable (`npm install`), should not be committed.
- Action: delete folder, add to `.gitignore`.

### 3) `backtests/` and `bob_runs/` (and `bob_runs.FROZEN_...`)
- Reason: historical outputs / run artifacts; not used by the live engine.
- Action: archive outside repo (or delete), add to `.gitignore` if you want them locally.

---

## B) Duplicate/variant copies (HIGH confidence)
These are alternate encodings/variants of the same engine and aren’t referenced by launch scripts.
- `auto_trade_futures_BADENC.py`
- `auto_trade_futures_UTF8.py`

If you keep one: keep only **`auto_trade_futures.py`**.

---

## C) Likely unused / not referenced by the live engine (MED-HIGH confidence)
Not imported by `auto_trade_futures.py` and not referenced by launcher scripts in this snapshot.

### Not referenced anywhere outside themselves
- `wop/` (separate framework)
- `utils/` (only self-references in this snapshot)
- `modules/` (single file `modules/sensory_matrix.py`, not imported by engine)
- `omnibrain/` (`omnibrain/web_ui.py` looks like a separate demo)
- `omnibrain-dashboard/` (single `apex_trade_memory.py`, not imported)
- `tools/apply_run.py` (not referenced)
- `app/` (Python/Flask demo UI; not used by engine)

If you are **only** running the futures engine, you can remove these.

---

## D) Broken/outdated scripts (MED confidence – safe to remove if you’re not using them)
These reference missing files/folders in the snapshot:
- `start_omnibrain.bat` (references `auto_trade.py` and `frontend/` which aren’t present)
- `run_bob_default.sh` / `progress_bob.sh` (reference `BOB_ASI_Pro_Plus.py` which isn’t present)
- `start_all_screen.sh` (references `/root/omnibrain2`, `governor/*`, and `bob.py` which aren’t present)
- `main.py` (imports `omnibrain_utils_futures` which isn’t present)

Also Python files with missing local imports:
- `OptimizerAI.py` (imports agents that don’t exist in `agents/`)
- `agent_swarm.py` (imports missing `agents.*` modules)
- `lab_worker.py` (imports missing `app.*` modules)

---

## E) Sensitive files (should not be in a public repo)
These were present in the snapshot. They are not “unused” but they are **unsafe** in Git:
- `REAL.json`
- `REALBOB.json`
- `TELEGRAM.TXT`
- `.bob_env`
- `.govbot.env`

Recommended: remove from repo and load secrets from VPS env/files that are gitignored.

---

## Suggested next step
If you confirm you ONLY run the futures engine (`auto_trade_futures.py`), I can:
1) Add a `.gitignore` that excludes caches/artifacts.
2) Delete the HIGH confidence folders/files above in a single commit.
3) Keep fingerprints + trade memory intact.
