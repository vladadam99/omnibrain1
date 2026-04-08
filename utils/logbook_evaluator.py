# -*- coding: utf-8 -*-
import pandas as pd
from tabulate import tabulate

LOG_FILE = "omnibrain_logbook.csv"

def load_trades():
    try:
        df = pd.read_csv(LOG_FILE, parse_dates=["timestamp"])
        df.sort_values(by="timestamp", inplace=True)
        return df
    except FileNotFoundError:
        print("❌ Logbook not found.")
        return None

def match_trades(df):
    matched = []
    open_trade = None

    for _, row in df.iterrows():
        if row["side"] == "BUY":
            open_trade = row
        elif row["side"] == "SELL" and open_trade is not None:
            # Ensure same symbol
            if row["symbol"] == open_trade["symbol"]:
                pnl = (row["price"] - open_trade["price"]) * open_trade["qty"]
                pct = (pnl / (open_trade["price"] * open_trade["qty"])) * 100
                matched.append({
                    "symbol": row["symbol"],
                    "entry_time": open_trade["timestamp"],
                    "exit_time": row["timestamp"],
                    "buy_price": open_trade["price"],
                    "sell_price": row["price"],
                    "qty": open_trade["qty"],
                    "pnl_usdt": round(pnl, 4),
                    "return_pct": round(pct, 2),
                    "signal": open_trade["signal"]
                })
                open_trade = None

    return pd.DataFrame(matched)

def display_summary(pairs):
    if pairs.empty:
        print("⚠️ No trade pairs to analyze.")
        return

    print("\n📈 Trade Pair Results (PnL)")
    print(tabulate(pairs.tail(10), headers="keys", tablefmt="grid", showindex=False))

    total = len(pairs)
    wins = (pairs["pnl_usdt"] > 0).sum()
    losses = (pairs["pnl_usdt"] <= 0).sum()
    win_rate = (wins / total) * 100 if total > 0 else 0
    total_pnl = pairs["pnl_usdt"].sum()
    avg_return = pairs["return_pct"].mean()

    print("\n📊 Performance Summary\n======================")
    print(f"Total trades:    {total}")
    print(f"  🟢 Wins:        {wins}")
    print(f"  🔴 Losses:      {losses}")
    print(f"  ✅ Win rate:    {win_rate:.2f}%")
    print(f"  💰 Total PnL:   {total_pnl:.4f} USDT")
    print(f"  📈 Avg Return:  {avg_return:.2f}%")

    strat_stats = pairs.groupby("signal").agg(
        trades=("pnl_usdt", "count"),
        wins=("pnl_usdt", lambda x: (x > 0).sum()),
        avg_pnl=("pnl_usdt", "mean"),
        avg_return=("return_pct", "mean")
    ).reset_index()

    print("\n🧠 Strategy Breakdown")
    print(tabulate(strat_stats, headers="keys", tablefmt="fancy_grid", showindex=False))

def main():
    df = load_trades()
    if df is not None and not df.empty:
        pairs = match_trades(df)
        display_summary(pairs)
    else:
        print("⚠️ No trades found in logbook.")

if __name__ == "__main__":
    main()
