# -*- coding: utf-8 -*-
import itertools
import numpy as np
import pandas as pd
import yfinance as yf
from app.swarm import MACDAgent, RSIAgent, SwarmManager

def backtest_with_params(macd_fast, macd_slow, rsi_lower, rsi_upper):
    aapl = yf.download('AAPL', period='1y', interval='1d', auto_adjust=True)
    tsla = yf.download('TSLA', period='1y', interval='1d', auto_adjust=True)
    price_data = {'AAPL': aapl, 'TSLA': tsla}

    # Pass fast/slow/signal into MACDAgent, lower/upper into RSIAgent
    agents = [
        MACDAgent('MACD_AAPL', 'AAPL', aapl,
                  fast=macd_fast, slow=macd_slow, signal=9),
        RSIAgent('RSI_AAPL', 'AAPL', aapl,
                 lower=rsi_lower, upper=rsi_upper),
        MACDAgent('MACD_TSLA', 'TSLA', tsla,
                  fast=macd_fast, slow=macd_slow, signal=9),
        RSIAgent('RSI_TSLA', 'TSLA', tsla,
                 lower=rsi_lower, upper=rsi_upper),
    ]

    swarm = SwarmManager(agents, price_dfs=price_data)
    swarm.run()

    # Use one strategy's series to compute Sharpe
    pnl_series = pd.Series([epoch['MACD_AAPL'] for epoch in swarm.performance_history])
    daily_rets = pnl_series.diff().fillna(0)
    sharpe = (np.sqrt(252) * daily_rets.mean() / daily_rets.std()
              if daily_rets.std() else 0.0)
    return swarm.performance_history[-1]['MACD_AAPL'], sharpe

if __name__ == '__main__':
    macd_fast_vals = [8, 12, 16]
    macd_slow_vals = [26, 30, 34]
    rsi_low_vals   = [20, 30, 40]
    rsi_high_vals  = [60, 70, 80]

    rows = []
    for fast, slow, low, high in itertools.product(macd_fast_vals,
                                                   macd_slow_vals,
                                                   rsi_low_vals,
                                                   rsi_high_vals):
        if fast >= slow or low >= high:
            continue
        final_pnl, sharpe = backtest_with_params(fast, slow, low, high)
        rows.append({
            'macd_fast': fast,
            'macd_slow': slow,
            'rsi_lower': low,
            'rsi_upper': high,
            'final_pnl': final_pnl,
            'sharpe': sharpe
        })
        print(f"Tested MACD({fast},{slow}) RSI({low},{high}) → P&L={final_pnl:.2f}, Sharpe={sharpe:.2f}")

    df = pd.DataFrame(rows)
    df.sort_values(['sharpe', 'final_pnl'], ascending=False, inplace=True)
    df.to_csv('param_optimization_results.csv', index=False)
    print("\nTop 5 configurations:")
    print(df.head(5))
