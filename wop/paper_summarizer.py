
# -*- coding: utf-8 -*-
"""
Summarize a paper trading CSV (time,symbol,action,side,price,qty,agent,pnl,note)
into a summary.json with the fields the Governor expects.

Usage:
  python -m governor_step4.paper_summarizer \
     --trades governor/candidates/<candidate_id>/paper_2d/trades.csv \
     --out governor/candidates/<candidate_id>/paper_2d/summary.json
"""
import argparse, csv, json, math
from pathlib import Path

def compute_metrics(csv_path: Path):
    trades = 0
    wins = 0
    losses = 0
    gross_win = 0.0
    gross_loss = 0.0
    realized = 0.0
    closes = 0

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            if (row.get("action") or "").upper() == "CLOSE":
                closes += 1
                pnl = float(row.get("pnl") or 0.0)
                realized += pnl
                if pnl > 0:
                    wins += 1; gross_win += pnl
                else:
                    losses += 1; gross_loss += abs(pnl)

    winrate = (wins / closes) if closes else 0.0
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win>0 else 0.0)
    # drawdown and sharpe_like require equity curve; we estimate with realized only (conservative)
    # you can replace with your engine's live equity series if available.
    summary = {
        "pnl_total": round(realized, 2),
        "winrate": round(winrate, 4),
        "profit_factor": round(profit_factor if math.isfinite(profit_factor) else 9999.0, 4),
        "trades": closes,
        "max_drawdown": None,
        "sharpe_like": None
    }
    return summary

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    csvp = Path(args.trades)
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    summary = compute_metrics(csvp)
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"[OK] Wrote {outp}")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
