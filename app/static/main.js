const socket = io();
let started = false;

socket.on('init', ctx => {
  // e.g. display symbol list in your UI
  initDashboard(ctx.symbols);
});

socket.on('update', ({ metrics, prices }) => {
  // called every second with fresh data
  updatePriceTicker(prices);
  updateMetricsTable(metrics);
  document.getElementById('last-updated').textContent = new Date().toISOString();
});

function start() {
  if (!started) {
    socket.emit('start');
    started = true;
  }
}
