from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.services.jobs import (
    CHEMX_DOMAINS,
    UPLOAD_DIR,
    analyze_source,
    cancel_job,
    create_job,
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

app = FastAPI(
    title="DataCon'26 ChemX Extractor",
    description="FastAPI web interface for ChemX dataset upload, live extraction and metrics.",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


class DemoJobRequest(BaseModel):
    domain: str = "Benzimidazoles"


@app.on_event("startup")
async def startup() -> None:
    prepare_storage()


@app.get("/", response_class=HTMLResponse)
async def upload_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "active": "upload", "domains": CHEMX_DOMAINS},
    )


@app.get("/realtime", response_class=HTMLResponse)
async def realtime_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "realtime.html",
        {"request": request, "active": "realtime", "domains": CHEMX_DOMAINS},
    )


@app.get("/metrics", response_class=HTMLResponse)
async def metrics_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "metrics.html",
        {"request": request, "active": "metrics", "domains": CHEMX_DOMAINS},
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/domains")
async def domains() -> dict[str, Any]:
    return {"domains": CHEMX_DOMAINS}


@app.get("/api/metrics")
async def metrics() -> dict[str, Any]:
    return metrics_payload()


@app.get("/api/jobs")
async def jobs() -> dict[str, Any]:
    return {"jobs": [summarize_job(job) for job in list_jobs()]}


@app.post("/api/demo-job")
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
    )
    asyncio.create_task(run_pipeline(job["id"]))
    return {"job": summarize_job(job)}


@app.post("/api/upload")
async def upload_dataset(
    dataset: UploadFile = File(...),
    domain: str = Form("Benzimidazoles"),
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

    saved_name = f"{Path(safe_name).stem}-{len(contents)}{Path(safe_name).suffix}"
    saved_path = UPLOAD_DIR / saved_name
    saved_path.write_bytes(contents)
    source = analyze_source(contents, safe_name)

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
    )
    asyncio.create_task(run_pipeline(job["id"]))
    return {"job": summarize_job(job)}


@app.get("/api/jobs/{job_id}")
async def job_detail(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": summarize_job(job)}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel(job_id: str) -> dict[str, Any]:
    if not cancel_job(job_id):
        raise HTTPException(status_code=409, detail="Job cannot be cancelled")
    job = get_job(job_id)
    return {"job": summarize_job(job)}


@app.get("/api/jobs/{job_id}/export.{export_format}")
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


@app.get("/api/jobs/{job_id}/events")
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
