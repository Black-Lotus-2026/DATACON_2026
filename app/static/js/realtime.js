const runTitle = document.querySelector("#run-title");
const runStatus = document.querySelector("#run-status");
const progressFill = document.querySelector("#progress-fill");
const progressValue = document.querySelector("#progress-value");
const stageLabel = document.querySelector("#stage-label");
const stageList = document.querySelector("#stage-list");
const recordsBody = document.querySelector("#records-body");
const logList = document.querySelector("#log-list");
const startDemo = document.querySelector("#start-demo");
const liveDomain = document.querySelector("#live-domain");
const metricPrecision = document.querySelector("#metric-precision");
const metricRecall = document.querySelector("#metric-recall");
const metricMacro = document.querySelector("#metric-macro");
const exportCsv = document.querySelector("#export-csv");
const exportJson = document.querySelector("#export-json");
const cancelRun = document.querySelector("#cancel-run");
const historyList = document.querySelector("#history-list");
const sourceGrid = document.querySelector("#source-grid");
const fieldMetricsBody = document.querySelector("#field-metrics-body");

const stages = [
  "Ingest",
  "PDF preprocessing",
  "Figure enrichment",
  "ChemX extraction",
  "Evaluation",
];

let source = null;
let activeJobId = null;

function currentJobId() {
  const params = new URLSearchParams(window.location.search);
  return params.get("job") || localStorage.getItem("chemx_current_job");
}

async function loadLatestJob() {
  const id = currentJobId();
  await loadJobsList();
  if (id) {
    connectToJob(id);
    return;
  }

  const response = await fetch("/api/jobs");
  const data = await response.json();
  if (data.jobs.length) {
    connectToJob(data.jobs[0].id);
  }
}

async function loadJobsList() {
  const response = await fetch("/api/jobs");
  const data = await response.json();
  renderJobsList(data.jobs || []);
}

function connectToJob(jobId) {
  if (source) {
    source.close();
  }
  activeJobId = jobId;
  localStorage.setItem("chemx_current_job", jobId);
  history.replaceState(null, "", `/realtime?job=${jobId}`);
  source = new EventSource(`/api/jobs/${jobId}/events`);
  source.onmessage = (event) => {
    const data = JSON.parse(event.data);
    renderJob(data.job);
    if (["completed", "failed", "cancelled", "interrupted"].includes(data.job.status)) {
      source.close();
      loadJobsList();
    }
  };
  source.onerror = () => {
    source.close();
    fetch(`/api/jobs/${jobId}`)
      .then((response) => response.json())
      .then((data) => renderJob(data.job))
      .then(loadJobsList)
      .catch(() => {});
  };
}

function renderJob(job) {
  activeJobId = job.id;
  runTitle.textContent = `${job.filename} · ${job.domain.name}`;
  runStatus.textContent = job.status;
  runStatus.dataset.status = job.status;
  progressFill.style.width = `${job.progress}%`;
  progressValue.textContent = `${job.progress}%`;
  stageLabel.textContent = job.stage?.title || "Queued";
  renderStages(job);
  renderRecords(job.records || []);
  renderLogs(job.logs || []);
  renderMetrics(job.metrics);
  renderFieldMetrics(job.metrics);
  renderSourceSummary(job.source_summary || {});
  renderExports(job);
  renderCancelState(job);
  markActiveHistory();
}

function renderStages(job) {
  stageList.innerHTML = stages.map((stage, index) => {
    const state = index < job.stage_index || job.status === "completed"
      ? "done"
      : index === job.stage_index && job.status === "running"
        ? "active"
        : "pending";
    const currentDetail = job.stage?.title === stage ? job.stage.detail : "";
    return `
      <article class="stage-item ${state}">
        <span>${index + 1}</span>
        <div>
          <strong>${stage}</strong>
          <small>${currentDetail || (state === "done" ? "Completed" : "Waiting")}</small>
        </div>
      </article>
    `;
  }).join("");
}

function renderRecords(records) {
  if (!records.length) {
    recordsBody.innerHTML = `<tr><td colspan="5">Записи появятся после этапа extraction.</td></tr>`;
    return;
  }
  recordsBody.innerHTML = records.map((record) => `
    <tr>
      <td>${escapeHtml(record.object_id)}</td>
      <td>${escapeHtml(record.primary_value)}</td>
      <td>${escapeHtml(record.property)}</td>
      <td>${escapeHtml(record.evidence)}</td>
      <td><span class="confidence">${escapeHtml(record.confidence)}</span></td>
    </tr>
  `).join("");
}

function renderLogs(logs) {
  logList.innerHTML = logs.slice().reverse().map((entry) => `
    <li>
      <span>${escapeHtml(entry.time)}</span>
      <strong>${escapeHtml(entry.message)}</strong>
    </li>
  `).join("");
}

function renderMetrics(metrics) {
  metricPrecision.textContent = metrics ? metrics.precision.toFixed(3) : "-";
  metricRecall.textContent = metrics ? metrics.recall.toFixed(3) : "-";
  metricMacro.textContent = metrics ? metrics.macro_f1.toFixed(3) : "-";
}

function renderFieldMetrics(metrics) {
  const fields = metrics?.fields || [];
  if (!fields.length) {
    fieldMetricsBody.innerHTML = `<tr><td colspan="4">Метрики появятся после evaluation.</td></tr>`;
    return;
  }
  fieldMetricsBody.innerHTML = fields.map((field) => `
    <tr>
      <td>${escapeHtml(field.name)}</td>
      <td>${field.precision.toFixed(3)}</td>
      <td>${field.recall.toFixed(3)}</td>
      <td>${field.f1.toFixed(3)}</td>
    </tr>
  `).join("");
}

function renderSourceSummary(summary) {
  const chips = [
    ["Tokens", summary.text_tokens ?? 0],
    ["Rows", summary.table_rows ?? 0],
    ["DOI", (summary.detected_dois || []).length],
    ["Properties", summary.detected_properties ?? 0],
    ["SMILES", summary.detected_smiles ?? 0],
  ];
  const notes = (summary.notes || []).slice(0, 3);
  sourceGrid.innerHTML = `
    ${chips.map(([label, value]) => `
      <div class="source-chip">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `).join("")}
    ${notes.length ? `<div class="source-notes">${notes.map((note) => `<p>${escapeHtml(note)}</p>`).join("")}</div>` : ""}
  `;
}

function renderExports(job) {
  const ready = job.status === "completed";
  setExportLink(exportCsv, ready ? `/api/jobs/${job.id}/export.csv` : "#", ready);
  setExportLink(exportJson, ready ? `/api/jobs/${job.id}/export.json` : "#", ready);
}

function setExportLink(link, href, enabled) {
  link.href = href;
  link.classList.toggle("is-disabled", !enabled);
  link.setAttribute("aria-disabled", enabled ? "false" : "true");
}

function renderCancelState(job) {
  const canCancel = ["queued", "running"].includes(job.status);
  cancelRun.disabled = !canCancel;
  cancelRun.classList.toggle("is-disabled", !canCancel);
}

function renderJobsList(jobs) {
  if (!jobs.length) {
    historyList.innerHTML = `<p class="empty-state">Нет запусков.</p>`;
    return;
  }
  historyList.innerHTML = jobs.slice(0, 12).map((job) => `
    <button class="history-item" type="button" data-job-id="${escapeHtml(job.id)}">
      <span>
        <strong>${escapeHtml(job.domain.name)}</strong>
        <small>${escapeHtml(job.filename)}</small>
      </span>
      <em data-status="${escapeHtml(job.status)}">${escapeHtml(job.status)}</em>
    </button>
  `).join("");
  markActiveHistory();
}

function markActiveHistory() {
  document.querySelectorAll(".history-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.jobId === activeJobId);
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

startDemo?.addEventListener("click", async () => {
  const response = await fetch("/api/demo-job", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({domain: liveDomain.value}),
  });
  const data = await response.json();
  if (!response.ok) {
    runTitle.textContent = data.detail || "Не удалось создать запуск";
    return;
  }
  await loadJobsList();
  connectToJob(data.job.id);
});

cancelRun?.addEventListener("click", async () => {
  if (!activeJobId || cancelRun.disabled) {
    return;
  }
  const response = await fetch(`/api/jobs/${activeJobId}/cancel`, {method: "POST"});
  if (response.ok) {
    const data = await response.json();
    renderJob(data.job);
    await loadJobsList();
  }
});

historyList?.addEventListener("click", (event) => {
  const item = event.target.closest(".history-item");
  if (!item) {
    return;
  }
  connectToJob(item.dataset.jobId);
});

[exportCsv, exportJson].forEach((link) => {
  link?.addEventListener("click", (event) => {
    if (link.getAttribute("aria-disabled") === "true") {
      event.preventDefault();
    }
  });
});

loadLatestJob();
