# -*- coding: utf-8 -*-
from flask import Flask, jsonify, render_template_string
import threading
import yfinance as yf
import pandas as pd
from swarm import SwarmManager, MACDAgent, RSIAgent

app = Flask(__name__)

# Run initial swarm training to build data for UI
# (In production, you'd run swarm in background or on schedule)

aapl_data = yf.download('AAPL', period='1y', interval='1d', auto_adjust=True)
tsla_data = yf.download('TSLA', period='1y', interval='1d', auto_adjust=True)

macd_agent = MACDAgent('MACD_AAPL', 'AAPL', aapl_data)
rsi_agent  = RSIAgent('RSI_TSLA', 'TSLA', tsla_data)
swarm = SwarmManager([macd_agent, rsi_agent])
# Train for a few epochs and keep history
swarm.train(5)

@app.route('/api/performance')
def api_performance():
    # Return last epoch performance
    perf = swarm.run_epoch()
    return jsonify(perf)

@app.route('/api/weights')
def api_weights():
    return jsonify(swarm.weight_history)

@app.route('/')
def index():
    # Simple HTML page fetching JSON
    html = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>OMNIBRAIN Dashboard</title>
    </head>
    <body>
      <h1>OMNIBRAIN Dashboard</h1>
      <div id="perf"></div>
      <div id="weights"></div>
      <script>
        fetch('/api/performance').then(r=>r.json()).then(data=>{
          document.getElementById('perf').innerHTML = '<h2>Latest Performance</h2><pre>'+JSON.stringify(data, null, 2)+'</pre>';
        });
        fetch('/api/weights').then(r=>r.json()).then(data=>{
          document.getElementById('weights').innerHTML = '<h2>Weight History</h2><pre>'+JSON.stringify(data, null, 2)+'</pre>';
        });
      </script>
    </body>
    </html>
    '''
    return render_template_string(html)

if __name__ == '__main__':
    # Run Flask in a separate thread or standalone
    app.run(debug=True, port=5000)
