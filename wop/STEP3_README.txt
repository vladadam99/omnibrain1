
UTF-8

STEP 3 — Wire PAPER == LIVE:

1) Use the mode-aware broker:
   In your engine code, update imports so calls route via the governor wrapper:

   BEFORE:
     from omnibrain_utils import futures_execute_trade, futures_close_trade, place_tp_sl_orders

   AFTER:
     from governor_step3.omnibrain_utils_governor import (
         futures_execute_trade, futures_close_trade, place_tp_sl_orders
     )

   (Keep your other omnibrain_utils imports unchanged.)

2) Telegram prefix everywhere:
   The wrapper prefixes all bot messages based on governor/config/modes.yaml via engine_hook.tg_prefix().

3) Running a PAPER session for a candidate:
   python governor_step3/governor_runner.py governor/candidates/<candidate_id>
   It writes trades to <candidate>/paper_2d/trades.csv.
   Your engine continues to send Telegram messages with [PAPER].

4) After 48h, summarize:
   Compute metrics from the CSV and write <candidate>/paper_2d/summary.json.
   Then proceed with the approval phrase YES LIVE <candidate_id>.

All files are UTF-8.
