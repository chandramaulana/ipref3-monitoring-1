(function () {
  const socket = io();
  const charts = window.NetworkCharts;

  const form = document.getElementById("testForm");
  const protocolSelect = document.getElementById("protocolSelect");
  const tcpFields = document.getElementById("tcpFields");
  const udpFields = document.getElementById("udpFields");
  const logConsole = document.getElementById("logConsole");
  const logFilter = document.getElementById("logFilter");

  const statusBadge = document.getElementById("systemStatusBadge");
  const realtimeIndicator = document.getElementById("realtimeIndicator");

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

  function setProtocolUI() {
    const protocol = protocolSelect.value;
    tcpFields.classList.toggle("d-none", protocol !== "TCP");
    udpFields.classList.toggle("d-none", protocol !== "UDP");
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

  async function startTest(evt) {
    evt.preventDefault();

    const fd = new FormData(form);
    const protocol = fd.get("protocol");

    const payload = {
      test_name: fd.get("test_name"),
      test_date: fd.get("test_date"),
      description: fd.get("description"),
      weather: fd.get("weather"),
      host: fd.get("host"),
      port: Number(fd.get("port")),
      protocol,
      sampling_interval: Number(protocol === "UDP" ? fd.get("duration_udp") : fd.get("duration")),
      auto_stop_minutes: Number(fd.get("auto_stop_minutes")),
      streams: Number(fd.get("streams")),
      mss: Number(fd.get("mss")),
      bandwidth: fd.get("bandwidth"),
      packet_size: Number(fd.get("packet_size")),
    };

    const res = await fetch("/api/test/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (!data.ok) {
      appendLog({ timestamp: new Date().toLocaleString(), level: "error", message: data.error || "Gagal start test" });
      return;
    }

    charts.reset();
    setStatus(true);
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
  protocolSelect.addEventListener("change", setProtocolUI);
  form.addEventListener("submit", startTest);

  charts.init();
  setProtocolUI();
  setSocketIndicator(socket.connected);
  refreshStatus();
})();
