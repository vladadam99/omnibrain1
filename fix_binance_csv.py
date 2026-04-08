# -*- coding: utf-8 -*-
import pandas as pd

# Column names for the raw Binance file (adapt if needed)
COLUMNS = [
    "timestamp", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "number_of_trades",
    "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
]

infile = "BTCTUSD-12h-2025-05.csv"
outfile = "sample_ohlcv.csv"

# Load CSV
df = pd.read_csv(infile, header=None, names=COLUMNS)

# Convert microseconds to datetime
df["timestamp"] = pd.to_datetime(df["timestamp"] // 1_000_000, unit="s")

# Save simplified OHLCV CSV
df_simple = df[["timestamp", "open", "high", "low", "close", "volume"]]
df_simple.to_csv(outfile, index=False)

print("✅ Saved:", outfile)
print(df_simple.head())
