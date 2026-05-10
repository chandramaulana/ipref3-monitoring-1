(function () {
  const tbody = document.querySelector("#historyTable tbody");
  const pageInfo = document.getElementById("pageInfo");
  const applyBtn = document.getElementById("applyFilter");
  const prevBtn = document.getElementById("prevPage");
  const nextBtn = document.getElementById("nextPage");

  const pageSize = 10;
  let records = [];
  let currentPage = 1;
  let sortKey = "start_time";
  let sortAsc = false;

  function q(id) {
    return document.getElementById(id).value.trim();
  }

  function queryParams() {
    const params = new URLSearchParams();
    if (q("filterProtocol")) params.set("protocol", q("filterProtocol"));
    if (q("filterName")) params.set("test_name", q("filterName"));
    if (q("filterHost")) params.set("host", q("filterHost"));
    if (q("filterDate")) params.set("date", q("filterDate"));
    if (q("filterSession")) params.set("session_id", q("filterSession"));
    return params;
  }

  function sortRecords() {
    records.sort((a, b) => {
      const x = (a[sortKey] || "").toString();
      const y = (b[sortKey] || "").toString();
      return sortAsc ? x.localeCompare(y) : y.localeCompare(x);
    });
  }

  function render() {
    sortRecords();
    const totalPages = Math.max(1, Math.ceil(records.length / pageSize));
    currentPage = Math.max(1, Math.min(currentPage, totalPages));

    const start = (currentPage - 1) * pageSize;
    const current = records.slice(start, start + pageSize);

    tbody.innerHTML = current.map((r) => `
      <tr>
        <td>${r.session_id || "-"}</td>
        <td>${r.test_name || "-"}</td>
        <td>${r.protocol || "-"}</td>
        <td>${r.host || "-"}</td>
        <td>${r.start_time || "-"}</td>
        <td>${r.status || "-"}</td>
        <td>
          <a class="btn btn-sm btn-outline-info" href="/report/${r.session_id}">Detail</a>
          <button class="btn btn-sm btn-outline-danger btn-delete ms-1" data-session-id="${r.session_id}">Hapus</button>
        </td>
      </tr>
    `).join("");

    pageInfo.textContent = `Page ${currentPage} / ${totalPages}`;
  }

  async function loadData() {
    const params = queryParams();
    const res = await fetch(`/api/history?${params.toString()}`);
    const data = await res.json();
    records = data.records || [];
    currentPage = 1;
    render();
  }

  applyBtn.addEventListener("click", loadData);
  prevBtn.addEventListener("click", () => {
    currentPage -= 1;
    render();
  });
  nextBtn.addEventListener("click", () => {
    currentPage += 1;
    render();
  });

  tbody.addEventListener("click", async (event) => {
    const target = event.target;
    if (!target.classList.contains("btn-delete")) {
      return;
    }

    const sessionId = target.dataset.sessionId;
    if (!sessionId) {
      return;
    }

    if (!window.confirm(`Hapus session ${sessionId}?`)) {
      return;
    }

    const res = await fetch(`/api/session/${sessionId}`, { method: "DELETE" });
    const data = await res.json();
    if (!data.ok) {
      window.alert(data.error || "Gagal menghapus session");
      return;
    }
    await loadData();
  });

  document.querySelectorAll("#historyTable thead th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (sortKey === key) {
        sortAsc = !sortAsc;
      } else {
        sortKey = key;
        sortAsc = true;
      }
      render();
    });
  });

  loadData();
})();
