
UTF-8

Files dropped:
- governor_step3/omnibrain_utils_governor.py
  * Routes trade actions through PAPER broker or LIVE client based on governor/config/modes.yaml.
  * Prefixes Telegram with [PAPER]/[LIVE].

- governor_step3/mode_toggle.py
  * One-liner to flip mode: PAPER or LIVE.
  * Writes governor/config/modes.yaml

Ensure Step 2 files exist:
- governor/engine_hook.py
- governor/paper_broker.py

Usage:
  python governor_step3/mode_toggle.py PAPER
  python governor_step3/mode_toggle.py LIVE
