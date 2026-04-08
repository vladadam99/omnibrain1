# -*- coding: utf-8 -*-
# --- equity_curve.py ---
import pandas as pd

def compute_equity_curve(trades_df, starting_balance=100000):
    """
    Generate equity curve from trades DataFrame.
    """
    equity = [starting_balance]
    timestamps = ["START"]

    for i, row in trades_df.iterrows():
        equity.append(equity[-1] + row["pnl"])
        timestamps.append(row["close_time"])

    equity_df = pd.DataFrame({"timestamp": timestamps[1:], "equity": equity[1:]})
    equity_df.set_index("timestamp", inplace=True)
    
    # Compute drawdowns
    equity_df["peak"] = equity_df["equity"].cummax()
    equity_df["drawdown"] = equity_df["equity"] - equity_df["peak"]
    equity_df["drawdown_pct"] = equity_df["drawdown"] / equity_df["peak"] * 100

    return equity_df
