# -*- coding: utf-8 -*-
def get_top_gainers(client, limit=30, volume_threshold=1000000):
    try:
        exchange_info = client.get_exchange_info()
        all_symbols = {
            s['symbol'] for s in exchange_info['symbols']
            if s['status'] == 'TRADING'
            and s['quoteAsset'] == 'USDT'
            and s['isSpotTradingAllowed']
        }

        tickers = client.get_ticker_24hr()
        gainers = []
        for t in tickers:
            symbol = t['symbol']
            if symbol not in all_symbols:
                continue  # Skip fake or non-spot
            try:
                price_change = float(t['priceChangePercent'])
                quote_volume = float(t['quoteVolume'])
                if quote_volume >= volume_threshold and price_change > 0:
                    gainers.append((symbol, price_change, quote_volume))
            except:
                continue

        gainers.sort(key=lambda x: (x[1], x[2]), reverse=True)
        return [g[0] for g in gainers[:limit]]

    except Exception as e:
        print(f"❌ Error during scanning: {e}")
        return []
