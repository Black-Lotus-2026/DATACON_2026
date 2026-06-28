from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.services.jobs import (
    CHEMX_DOMAINS,
    UPLOAD_DIR,
    analyze_source,
    cancel_job,
    create_job,
    default_model_config,
    domain_names,
    export_job,
    get_job,
    list_jobs,
    metrics_payload,
    prepare_storage,
    run_pipeline,
    safe_upload_name,
    summarize_job,
    validate_upload,
)

BASE_DIR = Path(__file__).resolve().parent

OPENAPI_TAGS = [
    {
        "name": "System",
        "description": "Readiness and static reference data for clients and monitors.",
    },
    {
        "name": "Upload",
        "description": "Create model-checking runs from PDFs, ZIP archives with PDFs and tabular/text fixtures.",
    },
    {
        "name": "Jobs",
        "description": "Inspect, stream, cancel and export ChemX extraction runs.",
    },
    {
        "name": "Metrics",
        "description": "Macro-F1 dashboard data across ChemX domains.",
    },
]

app = FastAPI(
    title="DataCon'26 ChemX Extractor",
    summary="FastAPI service for ChemX model checking.",
    description=(
        "Upload a single PDF or a ZIP archive containing PDFs, select a ChemX domain, "
        "attach an OpenAI-compatible model router configuration and monitor extraction quality in real time."
    ),
    version="0.1.0",
    contact={"name": "DataCon'26 ChemX"},
    openapi_tags=OPENAPI_TAGS,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    swagger_ui_parameters={
        "deepLinking": True,
        "displayRequestDuration": True,
        "docExpansion": "none",
        "filter": True,
        "persistAuthorization": True,
        "syntaxHighlight.theme": "obsidian",
        "tryItOutEnabled": True,
    },
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


class HealthResponse(BaseModel):
    status: str = Field(description="Service readiness state.", examples=["ok"])


class DomainsResponse(BaseModel):
    domains: list[dict[str, Any]]


class JobsResponse(BaseModel):
    jobs: list[dict[str, Any]]


class JobResponse(BaseModel):
    job: dict[str, Any]


class MetricsResponse(BaseModel):
    domains: list[dict[str, Any]]
    summary: dict[str, Any]


class ModelRouterSettings(BaseModel):
    router_url: str = Field(
        "",
        max_length=500,
        description="OpenAI-compatible base URL or internal model-router route.",
        examples=["https://api.vsegpt.ru/v1"],
    )
    api_key: str = Field("", max_length=500, description="API key for this run. It is never returned by the API.")
    model: str = Field("gpt-4.1", max_length=120, description="Primary model id.")
    review_model: str = Field("", max_length=120, description="Optional review model id.")
    pages_per_window: int = Field(4, ge=1, le=10, description="Pages sent per extraction pass.")
    send_images: bool = Field(True, description="Attach rendered page images when the model router supports vision.")
    review_pass: bool = Field(True, description="Run a second review pass for candidate records.")
    max_pages: int = Field(0, ge=0, le=500, description="0 means no explicit page cap.")


class DemoJobRequest(BaseModel):
    domain: str = "Benzimidazoles"
    model_router: ModelRouterSettings = Field(default_factory=ModelRouterSettings)


def normalize_model_config(
    *,
    router_url: str = "",
    api_key: str = "",
    model: str = "gpt-4.1",
    review_model: str = "",
    pages_per_window: int = 4,
    send_images: bool = True,
    review_pass: bool = True,
    max_pages: int = 0,
) -> dict[str, Any]:
    defaults = default_model_config()
    primary_model = (model or defaults["model"]).strip()[:120] or defaults["model"]
    max_pages_value = max(0, min(int(max_pages or 0), 500))
    return {
        "router_url": (router_url or "").strip()[:500],
        "api_key": (api_key or "").strip()[:500],
        "model": primary_model,
        "review_model": (review_model or "").strip()[:120],
        "pages_per_window": max(1, min(int(pages_per_window or defaults["pages_per_window"]), 10)),
        "send_images": bool(send_images),
        "review_pass": bool(review_pass),
        "max_pages": max_pages_value or None,
    }


@app.on_event("startup")
async def startup() -> None:
    prepare_storage()


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def upload_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "active": "upload", "domains": CHEMX_DOMAINS},
    )


@app.get("/realtime", response_class=HTMLResponse, include_in_schema=False)
async def realtime_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "realtime.html",
        {"request": request, "active": "realtime", "domains": CHEMX_DOMAINS},
    )


@app.get("/metrics", response_class=HTMLResponse, include_in_schema=False)
async def metrics_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "metrics.html",
        {"request": request, "active": "metrics", "domains": CHEMX_DOMAINS},
    )


@app.get("/docs", include_in_schema=False)
async def legacy_docs() -> RedirectResponse:
    return RedirectResponse(url="/api/docs")


@app.get("/api/health", tags=["System"], summary="Health check", response_model=HealthResponse)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/domains", tags=["System"], summary="List ChemX domains", response_model=DomainsResponse)
async def domains() -> dict[str, Any]:
    return {"domains": CHEMX_DOMAINS}


@app.get("/api/metrics", tags=["Metrics"], summary="Get aggregate ChemX metrics", response_model=MetricsResponse)
async def metrics() -> dict[str, Any]:
    return metrics_payload()


@app.get("/api/jobs", tags=["Jobs"], summary="List extraction jobs", response_model=JobsResponse)
async def jobs() -> dict[str, Any]:
    return {"jobs": [summarize_job(job) for job in list_jobs()]}


@app.post(
    "/api/demo-job",
    tags=["Upload"],
    summary="Create a demo extraction job",
    response_model=JobResponse,
    status_code=201,
)
async def demo_job(payload: DemoJobRequest) -> dict[str, Any]:
    if payload.domain not in domain_names():
        raise HTTPException(status_code=400, detail="Unknown ChemX domain")

    job = create_job(
        filename="chemx_demo_article.pdf",
        file_size=2_480_000,
        domain_name=payload.domain,
        source_type="demo",
        source_text=(
            "Benzimidazole derivative CC1=NC2=CC=CC=C2N1 showed MIC 0.5 ug/mL "
            "against S. aureus. A second compound O=C(NCC1=CC=CC=C1)N2CCOCC2 "
            "had pMIC 6.2 and solubility 1.8 mg/mL. DOI 10.1000/chemx.demo."
        ),
        source_summary={
            "text_tokens": 24,
            "table_rows": 0,
            "detected_dois": ["10.1000/chemx.demo"],
            "detected_properties": 3,
            "detected_smiles": 2,
            "notes": ["Demo source generated locally."],
        },
        model_config=normalize_model_config(**payload.model_router.model_dump()),
    )
    asyncio.create_task(run_pipeline(job["id"]))
    return {"job": summarize_job(job)}


@app.post(
    "/api/upload",
    tags=["Upload"],
    summary="Upload a PDF or ZIP archive and start extraction",
    response_model=JobResponse,
    status_code=201,
)
async def upload_dataset(
    dataset: UploadFile = File(
        ...,
        description="Single PDF or ZIP archive containing one or more PDFs. CSV, TSV, TXT and MD are accepted for fixtures.",
    ),
    domain: str = Form("Benzimidazoles", description="ChemX domain name."),
    model_router_url: str = Form("", description="OpenAI-compatible base URL or custom model router route."),
    model_api_key: str = Form("", description="API key for this run. It is not returned in job responses."),
    model: str = Form("gpt-4.1", description="Primary model id."),
    review_model: str = Form("", description="Optional review model id."),
    pages_per_window: int = Form(4, ge=1, le=10, description="Pages sent per extraction pass."),
    send_images: bool = Form(True, description="Attach rendered page images for vision-capable routers."),
    review_pass: bool = Form(True, description="Run review pass after extraction."),
    max_pages: int = Form(0, ge=0, le=500, description="0 means no explicit page cap."),
) -> dict[str, Any]:
    if domain not in domain_names():
        raise HTTPException(status_code=400, detail="Unknown ChemX domain")

    contents = await dataset.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    UPLOAD_DIR.mkdir(exist_ok=True)
    safe_name = safe_upload_name(dataset.filename or "dataset.bin")
    try:
        validate_upload(safe_name, len(contents))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        source = analyze_source(contents, safe_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    saved_name = f"{Path(safe_name).stem}-{len(contents)}{Path(safe_name).suffix}"
    saved_path = UPLOAD_DIR / saved_name
    saved_path.write_bytes(contents)
    model_config = normalize_model_config(
        router_url=model_router_url,
        api_key=model_api_key,
        model=model,
        review_model=review_model,
        pages_per_window=pages_per_window,
        send_images=send_images,
        review_pass=review_pass,
        max_pages=max_pages,
    )

    job = create_job(
        filename=safe_name,
        file_size=len(contents),
        domain_name=domain,
        source_type=Path(safe_name).suffix.lower().lstrip(".") or "binary",
        saved_path=str(saved_path),
        source_text=source["text"],
        source_summary=source["summary"],
        table_rows=source["table_rows"],
        preview_rows=source["preview_rows"],
        model_config=model_config,
    )
    asyncio.create_task(run_pipeline(job["id"]))
    return {"job": summarize_job(job)}


@app.get("/api/jobs/{job_id}", tags=["Jobs"], summary="Get job details", response_model=JobResponse)
async def job_detail(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": summarize_job(job)}


@app.post("/api/jobs/{job_id}/cancel", tags=["Jobs"], summary="Cancel a queued or running job", response_model=JobResponse)
async def cancel(job_id: str) -> dict[str, Any]:
    if not cancel_job(job_id):
        raise HTTPException(status_code=409, detail="Job cannot be cancelled")
    job = get_job(job_id)
    return {"job": summarize_job(job)}


@app.get("/api/jobs/{job_id}/export.{export_format}", tags=["Jobs"], summary="Export completed job artifacts")
async def export(job_id: str, export_format: str) -> Response:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail="Job is not completed yet")
    try:
        body, media_type, filename = export_job(job, export_format)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/jobs/{job_id}/events", tags=["Jobs"], summary="Stream job updates with Server-Sent Events")
async def job_events(job_id: str) -> StreamingResponse:
    if not get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    async def stream():
        previous = ""
        while True:
            job = get_job(job_id)
            if not job:
                yield "event: error\ndata: {}\n\n"
                break

            payload = json.dumps({"job": summarize_job(job)}, ensure_ascii=False)
            if payload != previous:
                yield f"data: {payload}\n\n"
                previous = payload

            if job["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.6)

    return StreamingResponse(stream(), media_type="text/event-stream")
