
UTF-8
This folder contains STEP 2 deliverables:
- paper_broker.py: virtual broker with identical interface (open/close/equity) and CSV logging.
- engine_hook.py: mode-aware Telegram prefix; helper to read PAPER/LIVE mode.
- bob_bundle_writer.py: produce candidate bundle (manifest + 2x30d summaries).
- paper_orchestrator.py: scaffold for 48h paper session; integrate with your engine loop to write trades & summary.
- telegram_bot_step2.py: Telegram approval phrase YES LIVE <candidate_id> and mode-prefixed messages.

Next:
1) Point your engine runner to read governor/config/modes.yaml and choose PaperBroker when mode==PAPER.
2) When a candidate passes 2x30d, call bob_bundle_writer.build_candidate_bundle(...) then POST /governor/propose.
3) Governor will trigger /governor/paper/start. Use paper_orchestrator.run_paper(...) to start the engine in PAPER and write outputs.
4) After 48h, send Telegram summary and wait for YES LIVE <candidate_id>. Then call /governor/promote.

All files are UTF-8.
