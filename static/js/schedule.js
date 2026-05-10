(function () {
  const form = document.getElementById("scheduleForm");
  const protocolSelect = document.getElementById("protocol");
  const tcpFields = document.getElementById("tcpFields");
  const udpFields = document.getElementById("udpFields");
  const tbody = document.querySelector("#tasksTable tbody");
  const runningInfo = document.getElementById("scheduleRunningInfo");
  const statusBadge = document.getElementById("scheduleStatus");

  function setProtocolFields() {
    const protocol = protocolSelect.value;
    tcpFields.classList.toggle("d-none", protocol !== "TCP");
    udpFields.classList.toggle("d-none", protocol !== "UDP");
  }

  function resetForm() {
    form.reset();
    document.getElementById("editTaskId").value = "";
    document.getElementById("saveTaskBtn").textContent = "Simpan Task";
    statusBadge.textContent = "Ready";
    setProtocolFields();
  }

  function collectPayload() {
    const protocol = document.getElementById("protocol").value;
    return {
      task_name: document.getElementById("taskName").value.trim(),
      scheduled_at: document.getElementById("scheduledAt").value,
      payload: {
        test_name: document.getElementById("testName").value.trim(),
        test_date: document.getElementById("testDate").value,
        description: document.getElementById("description").value.trim(),
        weather: document.getElementById("weather").value.trim(),
        host: document.getElementById("host").value.trim(),
        port: Number(document.getElementById("port").value),
        protocol,
        auto_stop_minutes: Number(document.getElementById("autoStop").value),
        sampling_interval: Number(document.getElementById("sampling").value),
        streams: Number(document.getElementById("streams").value),
        mss: Number(document.getElementById("mss").value),
        bandwidth: document.getElementById("bandwidth").value.trim(),
        packet_size: Number(document.getElementById("packetSize").value),
      },
    };
  }

  function renderTasks(tasks) {
    tbody.innerHTML = tasks.map((task) => `
      <tr>
        <td>${task.task_name || "-"}</td>
        <td>${task.scheduled_at || "-"}</td>
        <td>${task.status || "-"}</td>
        <td>${(task.payload || {}).test_name || "-"}</td>
        <td>
          <button class="btn btn-sm btn-outline-warning btn-edit" data-id="${task.id}">Edit</button>
          <button class="btn btn-sm btn-outline-danger btn-delete ms-1" data-id="${task.id}">Hapus</button>
        </td>
      </tr>
    `).join("");
  }

  async function fetchTasks() {
    const res = await fetch("/api/schedules");
    const data = await res.json();
    renderTasks(data.tasks || []);
  }

  async function fetchRunningStatus() {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (!data.running || !data.session) {
      runningInfo.textContent = "Belum ada task aktif.";
      return;
    }

    const source = data.session.trigger_source === "schedule" ? "Scheduled Task" : "Manual";
    const taskName = data.session.schedule_task_name || data.session.test_name || "-";
    runningInfo.textContent = `${taskName} | ${source} | ${data.session.protocol || "-"} | ${data.session.host || "-"}:${data.session.port || "-"}`;
  }

  async function submitTask(event) {
    event.preventDefault();
    const payload = collectPayload();
    const editTaskId = document.getElementById("editTaskId").value;

    const url = editTaskId ? `/api/schedules/${editTaskId}` : "/api/schedules";
    const method = editTaskId ? "PUT" : "POST";

    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (!data.ok) {
      window.alert(data.error || "Gagal menyimpan task");
      return;
    }

    resetForm();
    await fetchTasks();
  }

  async function loadTaskToForm(taskId) {
    const res = await fetch("/api/schedules");
    const data = await res.json();
    const task = (data.tasks || []).find((item) => item.id === taskId);
    if (!task) {
      return;
    }

    const payload = task.payload || {};
    document.getElementById("editTaskId").value = task.id;
    document.getElementById("taskName").value = task.task_name || "";
    document.getElementById("scheduledAt").value = task.scheduled_at || "";
    document.getElementById("testName").value = payload.test_name || "";
    document.getElementById("testDate").value = payload.test_date || "";
    document.getElementById("description").value = payload.description || "";
    document.getElementById("weather").value = payload.weather || "";
    document.getElementById("host").value = payload.host || "";
    document.getElementById("port").value = payload.port || 5201;
    document.getElementById("protocol").value = payload.protocol || "TCP";
    document.getElementById("autoStop").value = payload.auto_stop_minutes || 5;
    document.getElementById("sampling").value = payload.sampling_interval || 60;
    document.getElementById("streams").value = payload.streams || 1;
    document.getElementById("mss").value = payload.mss || 1518;
    document.getElementById("bandwidth").value = payload.bandwidth || "20M";
    document.getElementById("packetSize").value = payload.packet_size || 512;
    document.getElementById("saveTaskBtn").textContent = "Update Task";
    statusBadge.textContent = "Editing";
    setProtocolFields();
  }

  async function deleteTask(taskId) {
    if (!window.confirm("Hapus task ini?")) {
      return;
    }

    const res = await fetch(`/api/schedules/${taskId}`, { method: "DELETE" });
    const data = await res.json();
    if (!data.ok) {
      window.alert(data.error || "Gagal menghapus task");
      return;
    }

    await fetchTasks();
  }

  tbody.addEventListener("click", async (event) => {
    const target = event.target;
    if (target.classList.contains("btn-edit")) {
      await loadTaskToForm(target.dataset.id);
      return;
    }
    if (target.classList.contains("btn-delete")) {
      await deleteTask(target.dataset.id);
    }
  });

  document.getElementById("resetTaskBtn").addEventListener("click", resetForm);
  document.getElementById("refreshTasksBtn").addEventListener("click", fetchTasks);
  protocolSelect.addEventListener("change", setProtocolFields);
  form.addEventListener("submit", submitTask);

  setProtocolFields();
  fetchTasks();
  fetchRunningStatus();
  setInterval(fetchRunningStatus, 3000);
})();
