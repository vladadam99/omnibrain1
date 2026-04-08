# -*- coding: utf-8 -*-
import time
import logging
from datetime import datetime
from binance.spot import Spot
import pandas as pd

# --- CONFIG ---
API_KEY = "YOUR_REAL_KEY"
API_SECRET = "YOUR_REAL_SECRET"
CANDLE_INTERVAL = "1m"
LOOKBACK = 100
CONFIDENCE_THRESHOLD = 0.85
MIN_VOLUME_USDT = 10000000  # Minimum 24h volume to include symbol
TRADE_ALLOCATION_USDT = 5.0  # Amount of USDT to allocate per trade

# --- INIT ---
client = Spot(api_key=API_KEY, api_secret=API_SECRET)
logger = logging.getLogger("SWARM_CORE")
logging.basicConfig(level=logging.INFO)

# --- Agent Definitions ---
def RSI_AI(df):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    latest = rsi.iloc[-1]
    if latest < 30:
        return ("BUY", 0.9)
    elif latest > 70:
        return ("SELL", 0.9)
    else:
        return ("NEUTRAL", 0.5)

def MACD_AI(df):
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    latest = hist.iloc[-1]
    if latest > 0:
        return ("BUY", 0.8)
    elif latest < 0:
        return ("SELL", 0.8)
    else:
        return ("NEUTRAL", 0.5)

def BreakoutSniper(df):
    recent_high = df['high'].rolling(20).max().iloc[-1]
    recent_low = df['low'].rolling(20).min().iloc[-1]
    price = df['close'].iloc[-1]
    if price >= recent_high:
        return ("BUY", 0.88)
    elif price <= recent_low:
        return ("SELL", 0.88)
    else:
        return ("NEUTRAL", 0.4)

AGENTS = [RSI_AI, MACD_AI, BreakoutSniper]

# --- Utilities ---
def get_top_usdt_symbols():
    tickers = client.ticker_24hr()
    usdt_pairs = [t for t in tickers if t['symbol'].endswith('USDT') and not any(x in t['symbol'] for x in ['BUSD', 'USDC'])]
    filtered = [t['symbol'] for t in usdt_pairs if float(t['quoteVolume']) >= MIN_VOLUME_USDT]
    return filtered

def fetch_ohlcv(symbol):
    klines = client.klines(symbol, CANDLE_INTERVAL, limit=LOOKBACK)
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'])
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    return df[['close', 'high', 'low']]

def fuse_signals(signals):
    votes = {'BUY': 0, 'SELL': 0, 'NEUTRAL': 0}
    total_confidence = 0
    for action, conf in signals:
        votes[action] += conf
        total_confidence += conf
    top_action = max(votes, key=votes.get)
    avg_confidence = votes[top_action] / len(signals)
    return top_action, round(avg_confidence, 3)

def get_usdt_balance():
    balances = client.account()['balances']
    for asset in balances:
        if asset['asset'] == 'USDT':
            return float(asset['free'])
    return 0

def calculate_qty(symbol, allocation_usdt):
    price = float(client.ticker_price(symbol=symbol)['price'])
    return round(allocation_usdt / price, 6)

# --- Main Signal Engine ---
def swarm_signal_core():
    symbols = get_top_usdt_symbols()
    usdt_balance = get_usdt_balance()
    all_signals = []

    for symbol in symbols:
        try:
            if usdt_balance < TRADE_ALLOCATION_USDT:
                logger.warning("Insufficient USDT. Skipping remaining symbols.")
                break

            df = fetch_ohlcv(symbol)
            signals = [agent(df) for agent in AGENTS]
            action, confidence = fuse_signals(signals)
            logger.info(f"{symbol}: {action} ({confidence})")

            if action == "BUY" and confidence >= CONFIDENCE_THRESHOLD:
                qty = calculate_qty(symbol, TRADE_ALLOCATION_USDT)
                signal = {
                    'symbol': symbol,
                    'side': action,
                    'confidence': confidence,
                    'qty': qty,
                    'timestamp': datetime.utcnow().isoformat()
                }
                logger.info(f"Signal fired: {signal}")
                all_signals.append(signal)

        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")
    return all_signals

# --- Loop ---
if __name__ == "__main__":
    while True:
        swarm_signal_core()
        time.sleep(60)  # run every 1 minute
