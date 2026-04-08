
UTF-8

STEP 4 — Bob → Governor integration (2×30d + paper bundle)

WHAT'S INCLUDED
- bundle_from_existing.py
  Build a full candidate bundle from already-finished 30-day replays:
    python -m governor_step4.bundle_from_existing --run-dir runs/BOB_20251003_053052 --trial-id <trial_id> --engine-attrs path/to/engine_attrs.json

  Creates:
    governor/candidates/<candidate_id>/
      month30/pass_A/summary.json
      month30/pass_B/summary.json
      paper_2d/ (placeholders)
      manifest.json (awaiting_approval)

- paper_summarizer.py
  Turn paper_2d/trades.csv into paper_2d/summary.json for approval prompts:
    python -m governor_step4.paper_summarizer --trades governor/candidates/<cid>/paper_2d/trades.csv --out governor/candidates/<cid>/paper_2d/summary.json

- governor_client.py
  Minimal helper to call the API from scripts (propose/start/stop/promote).

HOW TO USE IN PRACTICE
1) Run your Bob month replays as usual.
2) Build candidate bundle from the two newest summary.json of a chosen trial:
   python -m governor_step4.bundle_from_existing --run-dir runs/BOB_... --trial-id <trial_id> --engine-attrs best_config_<runid>.json

3) (Optional) Also register with API to make the daemon see it:
   python - <<'PY'
import governor_step4.governor_client as gc
cid = gc.propose("<run_id>", "<trial_id>")
print("Proposed:", cid)
PY

4) Start paper for that candidate (48h):
   python - <<'PY'
import governor_step4.governor_client as gc
gc.start_paper("<candidate_id>", days=2)
# Then launch the engine in PAPER for this candidate:
#   python governor_step3/governor_runner.py governor/candidates/<candidate_id>
PY

5) After the 2 days, summarize paper:
   python -m governor_step4.paper_summarizer --trades governor/candidates/<cid>/paper_2d/trades.csv --out governor/candidates/<cid>/paper_2d/summary.json

6) Telegram bot sends approval prompt and you reply "YES LIVE <candidate_id>".
7) On approval, the bot calls /governor/promote and LIVE starts with this exact bundle.

All files are UTF-8.
