# -*- coding: utf-8 -*-
import yfinance as yf

def download_and_save(symbol, filename, period='1y', interval='1d'):
    print(f"Downloading {symbol} data...")
    data = yf.download(symbol, period=period, interval=interval)
    data.to_csv(filename)
    print(f"Saved to {filename}")

if __name__ == "__main__":
    download_and_save('AAPL', 'AAPL.csv')
    download_and_save('TSLA', 'TSLA.csv')
