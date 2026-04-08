# -*- coding: utf-8 -*-
class AlphaFilter:
    def __init__(self, min_confidence=0.8, min_confluence=2, volatility_threshold=0.5):
        self.min_confidence = min_confidence
        self.min_confluence = min_confluence
        self.volatility_threshold = volatility_threshold  # Placeholder, could be ATR%

    def filter_signals(self, signals, df):
        approved = []
        grouped = {"buy": [], "sell": []}

        for signal in signals:
            if signal["signal"] in ["buy", "sell"] and signal["confidence"] >= self.min_confidence:
                grouped[signal["signal"]].append(signal)

        for side in ["buy", "sell"]:
            if len(grouped[side]) >= self.min_confluence:
                # Optional: apply volatility filter
                if self._passes_volatility_filter(df):
                    approved.extend(grouped[side])

        return approved

    def _passes_volatility_filter(self, df):
        # Basic volatility check using standard deviation of close prices
        if df is None or len(df) < 10:
            return False
        std = df["close"].pct_change().std()
        return std >= self.volatility_threshold