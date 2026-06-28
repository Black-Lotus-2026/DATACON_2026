const uploadForm = document.querySelector("#upload-form");
const dropzone = document.querySelector("#dropzone");
const fileInput = document.querySelector("#dataset-file");
const fileName = document.querySelector("#file-name");
const fileMeta = document.querySelector("#file-meta");
const uploadState = document.querySelector("#upload-state");
const demoButton = document.querySelector("#demo-button");
const domainSelect = document.querySelector("#domain-select");
const domainTiles = document.querySelectorAll(".domain-tile");
const routerUrlInput = document.querySelector("#model-router-url");
const apiKeyInput = document.querySelector("#model-api-key");
const modelInput = document.querySelector("#model-id");
const reviewModelInput = document.querySelector("#review-model-id");
const pagesPerWindowInput = document.querySelector("#pages-per-window");
const maxPagesInput = document.querySelector("#max-pages");
const sendImagesInput = document.querySelector("#send-images");
const reviewPassInput = document.querySelector("#review-pass");
const routerFields = [
  routerUrlInput,
  apiKeyInput,
  modelInput,
  reviewModelInput,
  pagesPerWindowInput,
  maxPagesInput,
  sendImagesInput,
  reviewPassInput,
];

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
    fileName.textContent = "Выберите PDF или ZIP с PDF";
    fileMeta.textContent = "CSV, TSV, TXT and MD are also accepted for fixtures";
    return;
  }
  fileName.textContent = file.name;
  fileMeta.textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB`;
}

function modelRouterConfig() {
  return {
    router_url: routerUrlInput?.value.trim() || "",
    api_key: apiKeyInput?.value.trim() || "",
    model: modelInput?.value.trim() || "gpt-4.1",
    review_model: reviewModelInput?.value.trim() || "",
    pages_per_window: Number(pagesPerWindowInput?.value || 4),
    send_images: Boolean(sendImagesInput?.checked),
    review_pass: Boolean(reviewPassInput?.checked),
    max_pages: Number(maxPagesInput?.value || 0),
  };
}

function appendModelRouterPayload(payload) {
  const config = modelRouterConfig();
  payload.append("model_router_url", config.router_url);
  payload.append("model_api_key", config.api_key);
  payload.append("model", config.model);
  payload.append("review_model", config.review_model);
  payload.append("pages_per_window", String(config.pages_per_window));
  payload.append("send_images", String(config.send_images));
  payload.append("review_pass", String(config.review_pass));
  payload.append("max_pages", String(config.max_pages));
}

function persistModelRouterConfig() {
  const {api_key: _apiKey, ...safeConfig} = modelRouterConfig();
  localStorage.setItem("chemx_model_router", JSON.stringify(safeConfig));
}

function restoreModelRouterConfig() {
  try {
    const saved = JSON.parse(localStorage.getItem("chemx_model_router") || "{}");
    if (routerUrlInput && typeof saved.router_url === "string") routerUrlInput.value = saved.router_url;
    if (apiKeyInput) apiKeyInput.value = "";
    if (modelInput && typeof saved.model === "string") modelInput.value = saved.model || "gpt-4.1";
    if (reviewModelInput && typeof saved.review_model === "string") reviewModelInput.value = saved.review_model;
    if (pagesPerWindowInput && saved.pages_per_window) pagesPerWindowInput.value = saved.pages_per_window;
    if (maxPagesInput && Number.isInteger(saved.max_pages)) maxPagesInput.value = saved.max_pages;
    if (sendImagesInput && typeof saved.send_images === "boolean") sendImagesInput.checked = saved.send_images;
    if (reviewPassInput && typeof saved.review_pass === "boolean") reviewPassInput.checked = saved.review_pass;
  } catch {
    localStorage.removeItem("chemx_model_router");
  }
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
  appendModelRouterPayload(payload);
  persistModelRouterConfig();
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
      body: JSON.stringify({
        domain: domainSelect.value,
        model_router: modelRouterConfig(),
      }),
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

routerFields.forEach((field) => {
  field?.addEventListener("change", persistModelRouterConfig);
  field?.addEventListener("input", persistModelRouterConfig);
});

restoreModelRouterConfig();
syncDomainTiles();
