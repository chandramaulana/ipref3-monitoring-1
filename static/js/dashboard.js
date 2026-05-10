(function () {
  const socket = io();
  const charts = window.NetworkCharts;
  const logConsole = document.getElementById("logConsole");
  const logFilter = document.getElementById("logFilter");

  const statusBadge = document.getElementById("systemStatusBadge");
  const realtimeIndicator = document.getElementById("realtimeIndicator");
  const runningTaskInfo = document.getElementById("runningTaskInfo");

  const cards = {
    currentThroughput: document.getElementById("currentThroughput"),
    averageThroughput: document.getElementById("averageThroughput"),
    maxThroughput: document.getElementById("maxThroughput"),
    currentJitter: document.getElementById("currentJitter"),
    averageJitter: document.getElementById("averageJitter"),
    currentPacketLoss: document.getElementById("currentPacketLoss"),
    currentPing: document.getElementById("currentPing"),
    averagePing: document.getElementById("averagePing"),
  };

  const logBuffer = [];

  function setStatus(running) {
    statusBadge.textContent = running ? "Running" : "Idle";
    statusBadge.classList.toggle("bg-success", running);
  }

  function setSocketIndicator(connected) {
    realtimeIndicator.textContent = connected ? "WS ONLINE" : "WS OFFLINE";
    realtimeIndicator.classList.toggle("online", connected);
    realtimeIndicator.classList.toggle("offline", !connected);
  }

  function renderRunningTask(session) {
    if (!runningTaskInfo) {
      return;
    }
    if (!session) {
      runningTaskInfo.textContent = "Belum ada task aktif.";
      return;
    }

    const source = session.trigger_source === "schedule" ? "Scheduled Task" : "Manual";
    const taskName = session.schedule_task_name || session.test_name || "-";
    const proto = session.protocol || "-";
    const host = session.host || "-";
    runningTaskInfo.textContent = `${taskName} | ${source} | ${proto} | ${host}:${session.port || "-"}`;
  }

  function toText(value, suffix) {
    return `${Number(value || 0).toFixed(1)} ${suffix}`;
  }

  function updateCards(stats) {
    cards.currentThroughput.textContent = toText(stats.current_throughput, "Mbps");
    cards.averageThroughput.textContent = toText(stats.average_throughput, "Mbps");
    cards.maxThroughput.textContent = toText(stats.max_throughput, "Mbps");
    cards.currentJitter.textContent = toText(stats.current_jitter, "ms");
    cards.averageJitter.textContent = toText(stats.average_jitter, "ms");
    cards.currentPacketLoss.textContent = toText(stats.current_packet_loss, "%");
    cards.currentPing.textContent = toText(stats.current_ping, "ms");
    cards.averagePing.textContent = toText(stats.average_ping, "ms");
  }

  function appendLog(item) {
    logBuffer.push(item);
    if (logBuffer.length > 400) {
      logBuffer.shift();
    }
    renderLogs();
  }

  function renderLogs() {
    const selected = logFilter.value;
    const lines = logBuffer
      .filter((entry) => selected === "all" || entry.level === selected)
      .map((entry) => `[${entry.timestamp}] [${entry.level.toUpperCase()}] ${entry.message}`);

    logConsole.textContent = lines.join("\n");
    logConsole.scrollTop = logConsole.scrollHeight;
  }

  async function stopTest() {
    await fetch("/api/test/stop", { method: "POST" });
  }

  async function clearLogs() {
    await fetch("/api/logs/clear", { method: "POST" });
    logBuffer.length = 0;
    renderLogs();
  }

  function refreshStatus() {
    fetch("/api/status")
      .then((r) => r.json())
      .then((data) => {
        setStatus(data.running);
        renderRunningTask(data.session);
      });
  }

  socket.on("connect", () => {
    setSocketIndicator(true);
    appendLog({ timestamp: new Date().toLocaleString(), level: "system", message: "WebSocket connected" });
    refreshStatus();
  });

  socket.on("disconnect", () => {
    setSocketIndicator(false);
    appendLog({ timestamp: new Date().toLocaleString(), level: "error", message: "WebSocket disconnected" });
  });

  socket.on("status_update", (payload) => {
    setStatus(payload.running);
    renderRunningTask(payload.session || null);
  });

  socket.on("log_event", (payload) => appendLog(payload));

  socket.on("metric_update", (payload) => {
    charts.updateMetric(payload.metric);
    updateCards(payload.stats);
  });

  socket.on("ping_update", (payload) => {
    charts.updatePing(payload.ping_ms, payload.timestamp);
  });

  socket.on("session_complete", (payload) => {
    appendLog({ timestamp: new Date().toLocaleString(), level: "system", message: `Session ${payload.session_id} selesai` });
    setStatus(false);
  });

  document.getElementById("stopBtn").addEventListener("click", stopTest);
  document.getElementById("clearLogBtn").addEventListener("click", clearLogs);
  document.getElementById("refreshBtn").addEventListener("click", refreshStatus);
  logFilter.addEventListener("change", renderLogs);

  charts.init();
  setSocketIndicator(socket.connected);
  refreshStatus();
})();
