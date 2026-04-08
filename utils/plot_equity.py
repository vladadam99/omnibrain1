# -*- coding: utf-8 -*-
# --- plot_equity.py ---
import pandas as pd
import matplotlib.pyplot as plt
import os

def plot_equity_curve(csv_path="backtest_trades.csv", save_path="equity_curve.png"):
    if not os.path.exists(csv_path):
        print(f"[plot_equity] CSV file not found: {csv_path}")
        return

    df = pd.read_csv(csv_path)
    df["pnl_cumsum"] = df["pnl"].cumsum()
    df["timestamp"] = pd.to_datetime(df["close_time"])
    df = df.sort_values("timestamp")

    plt.figure(figsize=(12, 6))
    plt.plot(df["timestamp"], df["pnl_cumsum"], label="Equity Curve")
    plt.title("Equity Curve")
    plt.xlabel("Time")
    plt.ylabel("Cumulative PnL")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(save_path)
    print(f"[plot_equity] Equity curve saved as {save_path}")


def plot_drawdowns(csv_path="backtest_trades.csv", save_path="drawdown_curve.png"):
    if not os.path.exists(csv_path):
        print(f"[plot_drawdowns] CSV file not found: {csv_path}")
        return

    df = pd.read_csv(csv_path)
    df["pnl_cumsum"] = df["pnl"].cumsum()
    df["timestamp"] = pd.to_datetime(df["close_time"])
    df = df.sort_values("timestamp")

    equity = df["pnl_cumsum"]
    peak = equity.cummax()
    drawdown = equity - peak
    drawdown_pct = drawdown / peak * 100

    plt.figure(figsize=(12, 6))
    plt.plot(df["timestamp"], drawdown_pct, label="Drawdown (%)", color="red")
    plt.title("Drawdown Over Time")
    plt.xlabel("Time")
    plt.ylabel("Drawdown (%)")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(save_path)
    print(f"[plot_drawdowns] Drawdown chart saved as {save_path}")
