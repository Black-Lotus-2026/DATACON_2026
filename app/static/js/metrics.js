const trackedDomains = document.querySelector("#tracked-domains");
const completedRuns = document.querySelector("#completed-runs");
const totalRows = document.querySelector("#total-rows");
const avgBaseline = document.querySelector("#avg-baseline");
const avgCurrent = document.querySelector("#avg-projected");
const chart = document.querySelector("#bar-chart");
const metricsBody = document.querySelector("#metrics-body");

function formatScore(value) {
  return value == null ? "-" : Number(value).toFixed(3);
}

function formatRows(value) {
  return new Intl.NumberFormat("ru-RU").format(value);
}

function renderSummary(summary) {
  trackedDomains.textContent = summary.tracked_domains;
  completedRuns.textContent = summary.completed_runs;
  totalRows.textContent = formatRows(summary.total_rows);
  avgBaseline.textContent = formatScore(summary.avg_baseline);
  avgCurrent.textContent = formatScore(summary.avg_current ?? summary.avg_projected);
}

function renderChart(domains) {
  chart.innerHTML = domains.map((domain) => {
    const baselineWidth = Math.max(2, (domain.baseline || 0) * 100);
    const current = domain.current ?? domain.projected;
    const currentWidth = current == null ? 0 : Math.max(2, current * 100);
    return `
      <div class="bar-row">
        <span>${domain.name}</span>
        <div class="bars">
          <i class="bar baseline" style="width:${baselineWidth}%"></i>
          <i class="bar projected" style="width:${currentWidth}%"></i>
        </div>
        <strong>${formatScore(current)}</strong>
      </div>
    `;
  }).join("");
}

function renderTable(domains) {
  metricsBody.innerHTML = domains.map((domain) => {
    const deltaClass = domain.delta == null ? "" : domain.delta >= 0 ? "positive" : "negative";
    return `
      <tr>
        <td>${domain.name}</td>
        <td>${domain.track}</td>
        <td>${formatRows(domain.record_count || 0)}</td>
        <td>${formatScore(domain.baseline)}</td>
        <td>${formatScore(domain.current ?? domain.projected)}</td>
        <td><span class="delta ${deltaClass}">${domain.delta == null ? "-" : `+${formatScore(domain.delta)}`}</span></td>
        <td>${domain.job_id ? `<a class="table-link" href="/realtime?job=${domain.job_id}">${domain.status}</a>` : domain.status}</td>
      </tr>
    `;
  }).join("");
}

async function init() {
  const response = await fetch("/api/metrics");
  const data = await response.json();
  renderSummary(data.summary);
  renderChart(data.domains);
  renderTable(data.domains);
}

init();
