// === NewsSentimentPanel.js ===
import React, { useEffect, useState } from 'react';

export default function NewsSentimentPanel() {
  const [score, setScore] = useState(0.5);

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch('/api/sentiment');
        const data = await res.json();
        setScore(data.score);
      } catch {
        setScore(0.5);
      }
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  const label = score > 0.7 ? 'Greedy 🚀' : score < 0.3 ? 'Fearful 😨' : 'Neutral 😐';

  return (
    <div className="panel">
      <h2 className="title">Market Sentiment</h2>
      <p>Fear & Greed Score: <strong>{(score * 100).toFixed(0)}%</strong> – {label}</p>
    </div>
  );
}
