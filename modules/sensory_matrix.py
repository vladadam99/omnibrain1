# -*- coding: utf-8 -*-
# --- modules/sensory_matrix.py ---
import os
import pandas as pd
from datetime import datetime, timedelta

class SensoryMatrix:
    def __init__(self, symbol="BTCUSDT", interval="1h", lookback="30 days"):
        self.symbol = symbol.upper()
        self.interval = interval
        self.lookback = lookback

    def get_data(self):
        """
        Try to load local CSV data first. If unavailable, fallback to dummy generated data.
        """
        fname = f"data_{self.symbol}_{self.interval}.csv"
        if os.path.exists(fname):
            df = pd.read_csv(fname)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            return df

        print(f"[SensoryMatrix] Local file not found. Generating dummy OHLCV for {self.symbol}...")
        return self._generate_dummy_data()

    def _generate_dummy_data(self):
        """
        Generates dummy OHLCV data in case no file is found.
        """
        periods = self._lookback_to_periods()
        base_price = 10000
        data = []

        for i in range(periods):
            dt = datetime.now() - timedelta(hours=periods - i)
            open_price = base_price + i * 2
            high = open_price + 50
            low = open_price - 50
            close = open_price + (i % 3 - 1) * 20
            volume = 1000 + (i * 5)
            data.append([dt, open_price, high, low, close, volume])

        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df.set_index("timestamp", inplace=True)
        return df

    def _lookback_to_periods(self):
        """
        Converts lookback string (like '30 days') into number of 1h candles.
        """
        num, unit = self.lookback.strip().split()
        num = int(num)
        if "day" in unit:
            return num * 24
        elif "hour" in unit:
            return num
        else:
            return 720  # fallback default
