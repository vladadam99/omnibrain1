from flask import Flask, render_template, jsonify, request
import pandas as pd
import os, json
from datetime import datetime
from backtest_runner import run_backtest, run_single_strategy_backtest

app = Flask(__name__)

@app.route('/')
def index():
    config_path = os.path.join(os.getcwd(), "config.json")
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = json.load(f)

    trades_today = 0
    log_path = os.path.join(os.getcwd(), "trade_logs.csv")
    if os.path.exists(log_path):
        df = pd.read_csv(log_path)
        if "timestamp" in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            today = datetime.now().date()
            trades_today = df[df['timestamp'].dt.date == today].shape[0]
    trades_left = config.get("max_trades_per_day", 5) - trades_today

    return render_template("index.html", config=config, trades_today=trades_today, trades_left=trades_left)

@app.route('/opt')
def show_optimization():
    path = os.path.join(os.getcwd(), "param_optimization_results.csv")
    df = pd.read_csv(path)
    df = df.rename(columns={'rsi_lower':'rsi_low','rsi_upper':'rsi_high','final_pnl':'pnl'})
    heat = df.pivot_table(index='macd_fast',columns='macd_slow',values='sharpe',aggfunc='mean').fillna(0)
    x_labels = heat.columns.tolist()
    y_labels = heat.index.tolist()
    chart_data = []
    for i, row in enumerate(heat.values):
        for j, v in enumerate(row):
            chart_data.append({"x": x_labels[j], "y": y_labels[i], "v": round(v,2)})
    return render_template("opt.html", chart_data=chart_data, x_labels=x_labels, y_labels=y_labels)

@app.route('/top')
def top_strategies():
    path = os.path.join(os.getcwd(), "param_optimization_results.csv")
    df = pd.read_csv(path)
    df = df.rename(columns={'rsi_lower':'rsi_low','rsi_upper':'rsi_high','final_pnl':'pnl'})
    top_df = df.sort_values(by='sharpe', ascending=False).head(5)
    records = top_df[['macd_fast','macd_slow','rsi_low','rsi_high','pnl','sharpe']].round(3).to_dict(orient='records')
    return jsonify(records)

@app.route('/logs')
def logs():
    log_path = os.path.join(os.getcwd(), "trade_logs.csv")
    if not os.path.exists(log_path):
        return "<h3>📭 No trade logs found. Run your agent to generate logs.</h3>"
    df = pd.read_csv(log_path)
    table = df.to_html(classes='table table-dark table-striped', index=False)
    return f"""
    <html><head><title>Trade Logs</title>
    <link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'></head>
    <body style='background-color:#111;color:white;padding:2em;'>
    <h1>📜 OMNIBRAIN Trade Logs</h1>{table}
    <a href='/' class='btn btn-primary mt-3'>← Back to Dashboard</a>
    </body></html>
    """

@app.route('/agent')
def agent_status():
    status_path = os.path.join(os.getcwd(), "agent_status.json")
    if not os.path.exists(status_path):
        return "<h3>❌ No agent status found.</h3>"
    data = json.load(open(status_path))
    return f"""
    <html><head><title>Agent Status</title>
    <link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'></head>
    <body style='background-color:#111;color:white;padding:2em;'>
    <h1>🤖 OMNIBRAIN Agent Status</h1><ul class='list-group list-group-flush' style='color:white;'>
      <li class='list-group-item bg-dark'>Status: <strong>{data.get('status','unknown')}</strong></li>
      <li class='list-group-item bg-dark'>Active Strategy: <code>{data.get('active_strategy','-')}</code></li>
      <li class='list-group-item bg-dark'>Last Run: {data.get('last_run','-')}</li>
      <li class='list-group-item bg-dark'>Trades Today: {data.get('trades_today','-')}</li>
      <li class='list-group-item bg-dark'>Profit Today: ${data.get('profit_today','-')}</li>
      <li class='list-group-item bg-dark'>Win Rate: {data.get('win_rate','-')}%</li>
    </ul>
    <a href='/' class='btn btn-primary mt-3'>← Back to Dashboard</a>
    </body></html>
    """

@app.route('/config', methods=['GET'])
def config_view():
    config_path = os.path.join(os.getcwd(), "config.json")
    if not os.path.exists(config_path): return "<h3>❌ Config file not found.</h3>"
    config_data = json.load(open(config_path))
    return render_template("config.html", config=config_data)

@app.route('/save_config', methods=['POST'])
def save_config():
    config_path = os.path.join(os.getcwd(), "config.json")
    new = request.get_json()
    if 'max_trades_per_day' in new:
        try: new['max_trades_per_day'] = int(new['max_trades_per_day'])
        except: new['max_trades_per_day'] = 5
    if 'paper_trading' in new:
        new['paper_trading'] = str(new['paper_trading']).lower()=='true'
    json.dump(new, open(config_path, 'w'), indent=4)
    return "✅ Config saved!"

@app.route('/trade', methods=['GET','POST'])
def mock_trade():
    if request.method=='GET':
        cfg = json.load(open(os.path.join(os.getcwd(), "config.json"))) if os.path.exists(os.path.join(os.getcwd(), "config.json")) else {"default_symbol":"BTCUSDT","default_macd":[8,30],"default_rsi":[20,80]}
        return render_template("mock_trade.html", defaults=cfg)
    form = request.form
    entry, exit_p = float(form['entry']), float(form['exit'])
    pnl = round((exit_p - entry)*(1 if form['side']=='buy' else -1),2)
    trade = {"timestamp":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"symbol":form['symbol'],"strategy":form['strategy'],"side":form['side'],"entry":entry,"exit":exit_p,"pnl":pnl,"sharpe":2.4,"result":"win" if pnl>0 else "loss"}
    log = os.path.join(os.getcwd(),"trade_logs.csv")
    cols=["timestamp","symbol","strategy","side","entry","exit","pnl","sharpe","result"]
    import pandas as _pd; df=_pd.DataFrame([trade])[cols]
    df.to_csv(log, mode='a', index=False, header=not os.path.exists(log))
    return render_template("trade_result.html", trade=trade)

@app.route('/api/backtest')
def api_backtest():
    try:
        strats = request.args.getlist('strategy')
        start = request.args.get('start')
        end = request.args.get('end')
        symbol = request.args.get('symbol', "BTC/USDT")
        timeframe = request.args.get('timeframe', "1h")
        exch = request.args.get('exch', "binance")

        print(f"[api_backtest] strats={strats}, symbol={symbol}, tf={timeframe}, exch={exch}, start={start}, end={end}")

        result = run_backtest(strats, start, end, symbol=symbol, timeframe=timeframe, exch=exch)
        print("[DEBUG] Backtest result:", result)

        def series_to_dict(obj):
            if hasattr(obj, 'to_dict'):
                return obj.to_dict()
            return obj

        for k, v in result.items():
            if 'equity' in v:
                result[k]['equity'] = series_to_dict(v['equity'])
            if 'drawdown' in v:
                result[k]['drawdown'] = series_to_dict(v['drawdown'])

        return jsonify(result)

    except Exception as e:
        print(f"[ERROR] Backtest failed: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/backtest/trades')
def api_backtest_trades():
    strats = request.args.getlist('strategy')
    start = request.args.get('start')
    end = request.args.get('end')
    symbol = request.args.get('symbol', "BTC/USDT")
    timeframe = request.args.get('timeframe', "1h")
    exch = request.args.get('exch', "binance")
    if not strats:
        return jsonify([])
    trades, _, _ = run_single_strategy_backtest(strats[0], start, end, symbol=symbol, timeframe=timeframe, exch=exch)
    return jsonify(trades)

@app.route('/backtest')
def backtest_dashboard():
    config = json.load(open(os.path.join(os.getcwd(),"config.json"))) if os.path.exists(os.path.join(os.getcwd(),"config.json")) else {}
    return render_template("backtest.html", config=config)

if __name__ == '__main__':
    app.run(debug=True)
