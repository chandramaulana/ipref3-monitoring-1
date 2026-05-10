window.NetworkCharts = (function () {
  const MAX_POINTS = 120;
  const charts = {};

  function makeConfig(label, color) {
    return {
      type: "line",
      data: {
        labels: [],
        datasets: [{
          label,
          data: [],
          borderColor: color,
          backgroundColor: color + "33",
          borderWidth: 2,
          fill: true,
          tension: 0.28,
          pointRadius: 1.5,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          x: {
            ticks: { color: "#9bb0cf" },
            grid: { color: "rgba(255,255,255,0.06)" },
          },
          y: {
            ticks: { color: "#9bb0cf" },
            grid: { color: "rgba(255,255,255,0.06)" },
          },
        },
        plugins: {
          legend: {
            labels: {
              color: "#d9e7ff",
            },
          },
        },
      },
    };
  }

  function pushData(chart, label, value) {
    chart.data.labels.push(label);
    chart.data.datasets[0].data.push(value);

    if (chart.data.labels.length > MAX_POINTS) {
      chart.data.labels.shift();
      chart.data.datasets[0].data.shift();
    }
    chart.update();
  }

  function init() {
    charts.throughput = new Chart(document.getElementById("throughputChart"), makeConfig("Throughput Mbps", "#ff9f1c"));
    charts.jitter = new Chart(document.getElementById("jitterChart"), makeConfig("Jitter ms", "#4cc9f0"));
    charts.packetLoss = new Chart(document.getElementById("packetLossChart"), makeConfig("Packet Loss %", "#f72585"));
    charts.ping = new Chart(document.getElementById("pingChart"), makeConfig("Ping ms", "#80ed99"));
  }

  function updateMetric(metric) {
    const ts = metric.timestamp || new Date().toLocaleTimeString();
    pushData(charts.throughput, ts, metric.throughput_mbps || 0);
    pushData(charts.jitter, ts, metric.jitter_ms || 0);
    pushData(charts.packetLoss, ts, metric.packet_loss_percent || 0);
    if (metric.ping_ms !== undefined) {
      pushData(charts.ping, ts, metric.ping_ms || 0);
    }
  }

  function updatePing(ping, ts) {
    pushData(charts.ping, ts || new Date().toLocaleTimeString(), ping || 0);
  }

  function reset() {
    Object.values(charts).forEach((chart) => {
      chart.data.labels = [];
      chart.data.datasets[0].data = [];
      chart.update();
    });
  }

  return {
    init,
    updateMetric,
    updatePing,
    reset,
  };
})();
