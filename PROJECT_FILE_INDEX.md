# OMNIBRAIN Project File Index
_Generated: 2026-05-29 00:54:32Z (UTC)_
This index was generated from the uploaded project snapshot (`Omnibrain1-main.zip`). It’s meant to help quickly locate files and understand the repo structure.
## Summary
- Total files found: **2791**
- Files listed in this index (non-sensitive): **2787**
### Top-level folders (file counts)
| Folder | Files | Notes |
|---|---:|---|
| `.bt_cache` | 1704 | (bulky/cache; excluded from detailed listing below) |
| `node_modules` | 501 | (bulky/cache; excluded from detailed listing below) |
| `bob_runs` | 235 | (bulky/cache; excluded from detailed listing below) |
| `backtests` | 108 |  |
| `utils` | 54 |  |
| `wop` | 27 |  |
| `agents` | 14 |  |
| `data` | 13 |  |
| `templates` | 7 |  |
| `app` | 5 |  |
| `bob_runs.FROZEN_20251007_005307` | 4 |  |
| `.bob_env` | 1 |  |
| `.gitignore` | 1 |  |
| `.gitignore~` | 1 |  |
| `.govbot.env` | 1 |  |
| `.txt` | 1 |  |
| `AlphaFilterLayer.py` | 1 |  |
| `BOB_ASI_Pro_Plus_SANDBOX_UPG.py` | 1 |  |
| `New Text Document.txt` | 1 |  |
| `NewsSentimentPanel.js` | 1 |  |
| `OptimizerAI.py` | 1 |  |
| `README.md` | 1 |  |
| `REAL.json` | 1 |  |
| `REALBOB.json` | 1 |  |
| `TELEGRAM.TXT` | 1 |  |
| `__init__.py` | 1 |  |
| `adx_trend_agent.py` | 1 |  |
| `agent_sanity_check.py` | 1 |  |
| `agent_stats.pkl` | 1 |  |
| `agent_swarm.py` | 1 |  |
| `agent_winrate.json` | 1 |  |

## Sensitive files (excluded)
The following **filenames** were detected as potentially sensitive and are intentionally **not listed** in detail here. Keep them out of public repos.
- `.bob_env`
- `.govbot.env`
- `REAL.json`
- `REALBOB.json`
- `TELEGRAM.TXT`

## Key entry points & core scripts
- `auto_trade_futures.py`
- `main.py`
- `omnibrain_utils.py`
- `fingerprint_engine.py`
- `coin_scanner.py`
- `safe_fetch_helper.py`
- `bot_api.py`
- `analytics_api.py`
- `omnibrain_control.py`
- `omnibrain_sentinel.py`
- `OptimizerAI.py`
- `manager.sh`
- `start_all_screen.sh`
- `run_bob_default.sh`
- `requirements.txt`
- `package.json`

## agents/
- Files: **14**
  - `agents/__init__.py`
  - `agents/apex_config.py`
  - `agents/apex_microburst.py`
  - `agents/apex_momentum_pump.py`
  - `agents/apex_supertrend_adaptive.py`
  - `agents/apex_sweep_reversal.py`
  - `agents/apex_vwap_pullback.py`
  - `agents/dynamic_loader.py`
  - `agents/state/apex_microburst_last_signals.json`
  - `agents/state/apex_microburst_params.json`
  - `agents/state/apex_sweep_reversal_last_signals.json`
  - `agents/state/apex_sweep_reversal_params.json`
  - `agents/state/apex_vwap_pullback_last_signals.json`
  - `agents/state/apex_vwap_pullback_params.json`

## utils/
- Files: **54**
  - `utils/__init__.py`
  - `utils/__pycache__/__init__.cpython-310.pyc`
  - `utils/__pycache__/async_sl_monitor.cpython-310.pyc`
  - `utils/__pycache__/binance_futures_helper.cpython-310.pyc`
  - `utils/__pycache__/binance_rest_helper.cpython-310.pyc`
  - `utils/__pycache__/bot_state.cpython-310.pyc`
  - `utils/__pycache__/coin_scanner.cpython-310.pyc`
  - `utils/__pycache__/data_fetcher.cpython-310.pyc`
  - `utils/__pycache__/drawdown_guard.cpython-310.pyc`
  - `utils/__pycache__/eq_tracker.cpython-310.pyc`
  - `utils/__pycache__/futures_exec.cpython-310.pyc`
  - `utils/__pycache__/housekeeping.cpython-310.pyc`
  - `utils/__pycache__/logger.cpython-310.pyc`
  - `utils/__pycache__/pnl_calc.cpython-310.pyc`
  - `utils/__pycache__/position_reconcile.cpython-310.pyc`
  - `utils/__pycache__/risk_matrix.cpython-310.pyc`
  - `utils/__pycache__/sentiment.cpython-310.pyc`
  - `utils/__pycache__/sl_tp.cpython-310.pyc`
  - `utils/__pycache__/strategy_memory.cpython-310.pyc`
  - `utils/__pycache__/telegram_cmds.cpython-310.pyc`
  - `utils/__pycache__/timeframes.cpython-310.pyc`
  - `utils/__pycache__/top_movers.cpython-310.pyc`
  - `utils/__pycache__/trade_logger.cpython-310.pyc`
  - `utils/__pycache__/trade_memory.cpython-310.pyc`
  - `utils/__pycache__/utils.cpython-310.pyc`
  - `utils/async_sl_monitor.py`
  - `utils/binance_futures_helper.py`
  - `utils/binance_rest_helper.py`
  - `utils/bot_state.py`
  - `utils/coin_scanner.py`
  - `utils/data_fetcher.py`
  - `utils/drawdown_guard.py`
  - `utils/eq_tracker.py`
  - `utils/futures_exec.py`
  - `utils/housekeeping.py`
  - `utils/logger.py`
  - `utils/pnl_calc.py`
  - `utils/position_reconcile.py`
  - `utils/risk_matrix.py`
  - `utils/sentiment.py`
  - `utils/sl_tp.py`
  - `utils/strategy_memory.py`
  - `utils/telegram_cmds.py`
  - `utils/timeframes.py`
  - `utils/top_movers.py`
  - `utils/trade_logger.py`
  - `utils/trade_memory.py`
  - `utils/utils.py`

## backtests/
- Files: **108**
  - `backtests/2026-04-04_00-44-30__BTCUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__ETHUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__SOLUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__XRPUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__BNBUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__ADAUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__DOGEUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__TRXUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__AVAXUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__LINKUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__MATICUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__DOTUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__ATOMUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__LTCUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__BCHUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__NEARUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__FTMUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__ICPUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__FILUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__ETCUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__ALGOUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__XLMUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__APTUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__ARBUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__OPUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__SUIUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__IMXUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__INJUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__AAVEUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__GRTUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__RNDRUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__SANDUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__MANAUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__AXSUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__GALAUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__RUNEUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__KAVAUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__XECUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__COTIUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__ONEUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__ZILUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__DASHUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__ZECUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__XMRUSDT__apex_vwap_pullback__5m.csv`
  - `backtests/2026-04-04_00-44-30__ETCUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__ALGOUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__XLMUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__APTUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__ARBUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__OPUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__SUIUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__IMXUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__INJUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__AAVEUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__GRTUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__RNDRUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__SANDUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__MANAUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__AXSUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__GALAUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__RUNEUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__KAVAUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__XECUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__COTIUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__ONEUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__ZILUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__DASHUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__ZECUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__XMRUSDT__apex_microburst__5m.csv`
  - `backtests/2026-04-04_00-44-30__TRXUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__AVAXUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__LINKUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__MATICUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__DOTUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__ATOMUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__LTCUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__BCHUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__NEARUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__FTMUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__ICPUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__FILUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__ETCUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__ALGOUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__XLMUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__APTUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__ARBUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__OPUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__SUIUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__IMXUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__INJUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__AAVEUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__GRTUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__RNDRUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__SANDUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__MANAUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__AXSUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__GALAUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__RUNEUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__KAVAUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__XECUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__COTIUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__ONEUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__ZILUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__DASHUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__ZECUSDT__apex_sweep_reversal__5m.csv`
  - `backtests/2026-04-04_00-44-30__XMRUSDT__apex_sweep_reversal__5m.csv`

## data/
- Files: **13**
  - `data/.gitkeep`
  - `data/apex_memory.json`
  - `data/agent_thresholds.json`
  - `data/agent_winrate.json`
  - `data/coin_score_memory.json`
  - `data/equity_history.json`
  - `data/optimizer_memory.json`
  - `data/optimizer_tf_memory.json`
  - `data/performance.json`
  - `data/portfolio_state.json`
  - `data/session_state.json`
  - `data/sentiment_cache.json`
  - `data/trade_history.json`

## templates/
- Files: **7**
  - `templates/agent_config.json`
  - `templates/bot_config.json`
  - `templates/defaults.json`
  - `templates/symbols.json`
  - `templates/tf_defaults.json`
  - `templates/trade_template.json`
  - `templates/wallet.json`

## app/
- Files: **5**
  - `app/App.js`
  - `app/components/GlobalBotControl.js`
  - `app/components/LiveOpenPositions.js`
  - `app/components/OptimizerPanel.js`
  - `app/index.js`

## wop/
- Files: **27**
  - `wop/README.md`
  - `wop/bob_manager.py`
  - `wop/config.json`
  - `wop/requirements.txt`
  - `wop/run.py`
  - `wop/src/__init__.py`
  - `wop/src/agents/__init__.py`
  - `wop/src/agents/apex_microburst.py`
  - `wop/src/agents/apex_momentum_pump.py`
  - `wop/src/agents/apex_supertrend_adaptive.py`
  - `wop/src/agents/apex_sweep_reversal.py`
  - `wop/src/agents/apex_vwap_pullback.py`
  - `wop/src/core/__init__.py`
  - `wop/src/core/execution.py`
  - `wop/src/core/footprints.py`
  - `wop/src/core/risk.py`
  - `wop/src/core/state.py`
  - `wop/src/core/telemetry.py`
  - `wop/src/core/universe.py`
  - `wop/src/data/__init__.py`
  - `wop/src/data/features.py`
  - `wop/src/data/feeds.py`
  - `wop/src/data/filters.py`
  - `wop/src/data/ohlcv.py`
  - `wop/src/data/sentiment.py`
  - `wop/src/data/symbols.py`
  - `wop/src/utils/__init__.py`

## Root-level files (selected)
Showing up to 120 root-level files (non-sensitive). Total root files: **110**.
  - `.gitignore`
  - `.gitignore~`
  - `.txt`
  - `AlphaFilterLayer.py`
  - `BOB_ASI_Pro_Plus_SANDBOX_UPG.py`
  - `New Text Document.txt`
  - `NewsSentimentPanel.js`
  - `OptimizerAI.py`
  - `README.md`
  - `__init__.py`
  - `adx_trend_agent.py`
  - `agent_sanity_check.py`
  - `agent_stats.pkl`
  - `agent_swarm.py`
  - `agent_winrate.json`
  - `all_signals_log.csv`
  - `analytics_api.py`
  - `auto_trade_futures.py`
  - `auto_trade_futures_BADENC.py`
  - `auto_trade_futures_UTF8.py`
  - `backtest_autotrade.py`
  - `bot_api.py`
  - `check_balance_and_trades.py`
  - `coin_scanner.py`
  - `config.json`
  - `config.py`
  - `config.yaml`
  - `daily_pnl.csv`
  - `data.txt`
  - `data_fetcher.py`
  - `download_data.py`
  - `equity_curve.csv`
  - `equity_history.json`
  - `equity_log.csv`
  - `equity_log.json`
  - `equity_tracker.py`
  - `fingerprint_engine.py`
  - `fingerprint_guard.py`
  - `fingerprints_losses.jsonl`
  - `fingerprints_wins.jsonl`
  - `fix_binance_csv.py`
  - `force_close_positions.py`
  - `force_sell_by_balance.py`
  - `fp_sim_standalone.py`
  - `fractal_flux_strategy.py`
  - `gridtrader_agent.py`
  - `hourly_strategy_map.json`
  - `hyperloop_extractor_strategy.py`
  - `jsconfig.json`
  - `lab_adapters.py`
  - `lab_worker.py`
  - `live_config.yaml`
  - `main.py`
  - `manage_bot.sh.bak`
  - `manager.sh`
  - `multi_timeframe_vote.py`
  - `omnibot_runner.py`
  - `omnibrain_control.py`
  - `omnibrain_full_dump.txt`
  - `omnibrain_heartbeat.txt`
  - `omnibrain_logbook.csv`
  - `omnibrain_sentinel.py`
  - `omnibrain_telegram_ai.py`
  - `omnibrain_trades.log`
  - `omnibrain_utils.py`
  - `open_positions.json`
  - `opt.html`
  - `optimizer_memory.json`
  - `optimizer_results.csv`
  - `optimizer_tf_memory.json`
  - `package-lock.json`
  - `package.json`
  - `paper_trades.csv`
  - `param_optimization_results.csv`
  - `patch_safe_fetch.sh`
  - `patch_web_ui.md`
  - `persistent_resume.py`
  - `portfolio.py`
  - `priceaction_agent.py`
  - `progress_bob.sh`
  - `requirements.txt`
  - `resume_manager.py`
  - `rsi_2_agent.py`
  - `run_bob_default.sh`
  - `safe_fetch_helper.py`
  - `sample_ohlcv.csv`
  - `skipped_coins.log`
  - `start_all_screen.sh`
  - `start_omnibrain.bat`
  - `strategy_memory.csv`
  - `summarize_bob_runs.sh`
  - `swarm_signal_core.py`
  - `test_openai.py`
  - `trade_log.csv`
  - `trade_log.json`
  - `trade_memory.jsonl`
  - `trade_memory.py`
  - `trades.csv`
  - `trailing_stop_utils.py`

## Bulky folders not expanded
- `.bt_cache/` (1704 files) — typically cache/build artifacts. Consider adding to `.gitignore` if not already.
- `bob_runs/` (235 files) — typically cache/build artifacts. Consider adding to `.gitignore` if not already.
- `node_modules/` (501 files) — typically cache/build artifacts. Consider adding to `.gitignore` if not already.

## How to regenerate this index
On your machine/VPS:
```bash
cd <repo>
python - << 'PY'
import os
for dp,_,fs in os.walk('.'):
    for f in fs:
        print(os.path.join(dp,f))
PY
```
