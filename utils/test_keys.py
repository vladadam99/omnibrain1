# -*- coding: utf-8 -*-
import asyncio
from binance import AsyncClient

# Your testnet keys directly inserted here
BINANCE_TESTNET_API_KEY = "ce7e7ffdbf5e8e911c7fc5e10763561d4b18232daa95652e38b6e929754b2224"
BINANCE_TESTNET_API_SECRET = "6531a4b804cb7cf292e0a5f323bf644064773ed0d745835597aba8716eb3e391"

async def test_keys():
    client = await AsyncClient.create(
        api_key=BINANCE_TESTNET_API_KEY,
        api_secret=BINANCE_TESTNET_API_SECRET,
        testnet=True
    )
    try:
        account = await client.get_account()
        print("Account info keys valid. Balances:")
        for b in account['balances']:
            if float(b['free']) > 0:
                print(f"{b['asset']}: {b['free']}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await client.close_connection()

asyncio.run(test_keys())
