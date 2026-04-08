# -*- coding: utf-8 -*-
# sentiment_ai.py — OMNIBRAIN Sentiment Intelligence Core

import requests
import datetime

class SentimentAI:
    def __init__(self):
        self.sources = [
            "https://cryptopanic.com/api/v1/posts/?auth_token=demo&public=true",
        ]

    def fetch_sentiment(self):
        results = []
        for url in self.sources:
            try:
                res = requests.get(url)
                data = res.json()
                for post in data.get("results", []):
                    title = post.get("title", "")
                    published_at = post.get("published_at", "")
                    votes = post.get("votes", {})
                    sentiment = self.classify(votes)
                    results.append({
                        "title": title,
                        "timestamp": published_at,
                        "sentiment": sentiment
                    })
            except Exception as e:
                print("❌ Sentiment fetch failed:", str(e))
        return results

    def classify(self, votes):
        up = votes.get("positive", 0)
        down = votes.get("negative", 0)
        if up > down:
            return "positive"
        elif down > up:
            return "negative"
        return "neutral"

# === Example ===
if __name__ == "__main__":
    sai = SentimentAI()
    news = sai.fetch_sentiment()
    for n in news[:5]:
        print(f"[{n['sentiment'].upper()}] {n['timestamp']} - {n['title']}")
