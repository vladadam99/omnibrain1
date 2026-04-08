# -*- coding: utf-8 -*-
import pandas as pd
import datetime as dt
from binance.client import Client

class SensoryMatrix:
    def __init__(self, symbol, interval, lookback):
        self.symbol = symbol
        self.interval = interval
        self.lookback = lookback
        self.client = Client(
            "ce7e7ffdbf5e8e911c7fc5e10763561d4b18232daa95652e38b6e929754b2224",
            "6531a4b804cb7cf292e0a5f323bf644064773ed0d745835597aba8716eb3e391",
            testnet=True
        )

    def get_data(self):
        try:
            print(f"[INFO] Fetching {self.lookback} of {self.symbol} ({self.interval}) from Binance...")
            klines = self.client.get_klines(symbol=self.symbol, interval=self.interval)
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore'
            ])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df = df.astype(float, errors='ignore')
            return df.tail(100)
        except Exception as e:
            print(f"[Data Error] {e}")
            return pd.DataFrame()
