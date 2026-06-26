const uploadForm = document.querySelector("#upload-form");
const dropzone = document.querySelector("#dropzone");
const fileInput = document.querySelector("#dataset-file");
const fileName = document.querySelector("#file-name");
const fileMeta = document.querySelector("#file-meta");
const uploadState = document.querySelector("#upload-state");
const demoButton = document.querySelector("#demo-button");
const domainSelect = document.querySelector("#domain-select");
const domainTiles = document.querySelectorAll(".domain-tile");

function setState(message, isError = false) {
  uploadState.textContent = message;
  uploadState.classList.toggle("is-error", isError);
}

function syncDomainTiles() {
  domainTiles.forEach((tile) => {
    tile.classList.toggle("is-selected", tile.dataset.domain === domainSelect.value);
  });
}

function updateFileLabel(file) {
  if (!file) {
    fileName.textContent = "Выберите PDF, CSV, TSV, TXT, MD или ZIP";
    fileMeta.textContent = "ChemX article, table export, text source or packaged dataset";
    return;
  }
  fileName.textContent = file.name;
  fileMeta.textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB`;
}

dropzone?.addEventListener("click", () => fileInput.click());
dropzone?.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    fileInput.click();
  }
});
dropzone?.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropzone.classList.add("is-dragging");
});
dropzone?.addEventListener("dragleave", () => dropzone.classList.remove("is-dragging"));
dropzone?.addEventListener("drop", (event) => {
  event.preventDefault();
  dropzone.classList.remove("is-dragging");
  const file = event.dataTransfer.files[0];
  if (file) {
    fileInput.files = event.dataTransfer.files;
    updateFileLabel(file);
  }
});

fileInput?.addEventListener("change", () => updateFileLabel(fileInput.files[0]));
domainSelect?.addEventListener("change", syncDomainTiles);
domainTiles.forEach((tile) => {
  tile.addEventListener("click", () => {
    domainSelect.value = tile.dataset.domain;
    syncDomainTiles();
  });
});

uploadForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = fileInput.files[0];
  if (!file) {
    setState("Файл не выбран.", true);
    return;
  }

  const payload = new FormData();
  payload.append("dataset", file);
  payload.append("domain", domainSelect.value);
  setState("Загрузка и запуск пайплайна...");

  try {
    const response = await fetch("/api/upload", {
      method: "POST",
      body: payload,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Upload failed");
    }
    localStorage.setItem("chemx_current_job", data.job.id);
    window.location.href = `/realtime?job=${data.job.id}`;
  } catch (error) {
    setState(error.message, true);
  }
});

demoButton?.addEventListener("click", async () => {
  setState("Создаю demo job...");
  try {
    const response = await fetch("/api/demo-job", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({domain: domainSelect.value}),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Demo failed");
    }
    localStorage.setItem("chemx_current_job", data.job.id);
    window.location.href = `/realtime?job=${data.job.id}`;
  } catch (error) {
    setState(error.message, true);
  }
});

syncDomainTiles();
