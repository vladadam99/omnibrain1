--- web_ui.py
+++ web_ui.py
@@ -1,6 +1,11 @@
 from flask import Flask, render_template
 from swarm import SwarmManager, MACDAgent, RSIAgent
 import yfinance as yf

 app = Flask(__name__)

+# Download data once
+aapl = yf.download('AAPL', period='1y', interval='1d', auto_adjust=True)
+tsla = yf.download('TSLA', period='1y', interval='1d', auto_adjust=True)

 agents = [
     MACDAgent('MACD_AAPL', 'AAPL', aapl),
     RSIAgent('RSI_TSLA', 'TSLA', tsla)
 ]
 swarm = SwarmManager(agents)

-# Pre-run epochs to build history
-NUM_EPOCHS = 5
-performance_history = []
-for _ in range(NUM_EPOCHS):
-    perf = swarm.run_epoch()
-    performance_history.append(perf)
+# Pre-run epochs to build both weight and performance history
+NUM_EPOCHS = 5
+performance_history = []
+for _ in range(NUM_EPOCHS):
+    perf = swarm.run_epoch()
+    performance_history.append(perf)

 @app.route('/')
 def index():
-    return render_template(
-        'index.html',
-        performance=swarm.evaluator.evaluate(),
-        weight_history=swarm.weight_history,
-        performance_history=performance_history
-    )
+    return render_template(
+        'index.html',
+        performance=swarm.evaluator.evaluate(),
+        weight_history=swarm.weight_history,
+        performance_history=performance_history
+    )

 if __name__ == '__main__':
     app.run(debug=True)
--- templates/index.html
+++ templates/index.html
@@ -20,6 +20,9 @@
     <canvas id="weightChart" height="100"></canvas>

+    <h2 class="mt-5">Cumulative P&L History</h2>
+    <canvas id="perfChart" height="100"></canvas>
+
   </div>

   <script>
@@ -50,6 +53,33 @@
     );

+    // Prepare performance-history datasets
+    const perfDatasets = [
+      {% for strat in performance_history[0].keys() %}
+      {
+        label: '{{ strat }}',
+        data: [
+          {% for perf in performance_history %}
+            {{ perf[strat] }}{{ loop.last ? '' : ',' }}
+          {% endfor %}
+        ],
+        tension: 0.3,
+        fill: false
+      }{{ loop.last ? '' : ',' }}
+      {% endfor %}
+    ];
+
+    new Chart(
+      document.getElementById('perfChart').getContext('2d'),
+      {
+        type: 'line',
+        data: { labels: epochs, datasets: perfDatasets },
+        options: {
+          responsive: true,
+          scales: { y: { title: { display: true, text: 'Cumulative P&L' } } }
+        }
+      }
+    );

