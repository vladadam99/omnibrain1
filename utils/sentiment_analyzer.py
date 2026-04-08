# -*- coding: utf-8 -*-
import aiohttp
import logging

class SentimentAnalyzer:
    def __init__(self):
        self.news_sentiment = 0.0
        self.social_sentiment = 0.0
        self.fear_greed_index = 0.5  # 0 to 1, 1 = max greed

    async def update(self):
        try:
            async with aiohttp.ClientSession() as session:
                # Example API calls - replace with your actual APIs and keys
                news_url = "https://api.example.com/news_sentiment"
                social_url = "https://api.example.com/social_sentiment"
                fear_greed_url = "https://api.example.com/fear_greed"

                async with session.get(news_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.news_sentiment = data.get("score", 0.0)

                async with session.get(social_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.social_sentiment = data.get("score", 0.0)

                async with session.get(fear_greed_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.fear_greed_index = data.get("value", 50) / 100

        except Exception as e:
            logging.error(f"SentimentAnalyzer update error: {e}")

    def combined_sentiment_score(self):
        # Combine news + social + fear/greed indices with weights
        combined = (0.4 * self.news_sentiment + 0.4 * self.social_sentiment + 0.2 * self.fear_greed_index)
        # Clamp between -0.5 and 0.5 roughly, normalized to -0.5..0.5 range
        return max(min(combined, 0.5), -0.5)
