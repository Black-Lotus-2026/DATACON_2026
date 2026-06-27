from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datacon_agent.pdf import DocumentContext, PageContext, load_pdf, table_to_markdown


DEFAULT_SCRAPER_DIR = Path("runs/datacon_agent_scrapes")


@dataclass(frozen=True)
class ScraperPipelineConfig:
    scraper_dir: str | Path | None = None
    scrape_sqlite: str | Path | None = None
    overwrite_scrape: bool = False
    run_visual: bool = False
    visual_provider: str = "heuristic"
    visual_limit: int | None = None
    run_ocsr: bool = False
    ocsr_provider: str = "molscribe"
    ocsr_detector_provider: str | None = None
    ocsr_limit: int | None = None
    ocsr_rerun: bool = False
    ocsr_batch_size: int = 8
    ocsr_device: str = "cpu"
    ocsr_min_confidence: float = 0.0
    run_chemical_agents: bool = False
    chemical_agent_dir: str | Path | None = None
    chemical_env_file: str | Path = ".env"
    chemical_llm_provider: str = "vsegpt"
    chemical_llm_base_url: str | None = None
    chemical_data_model: str | None = None
    chemical_model: str | None = None
    chemical_temperature: float = 0.01
    chemical_max_tokens: int = 1800
    chemical_timeout: float = 180.0
    chemical_data_limit: int | None = None
    chemical_limit: int | None = None
    chemical_max_crops_per_figure: int = 12
    chemical_no_response_format: bool = False


def scrape_pdf_to_document(
    pdf_path: str | Path,
    *,
    scraper_dir: str | Path | None = None,
    scrape_sqlite: str | Path | None = None,
    overwrite: bool = False,
    render_pages: bool = True,
    dpi: int = 160,
    config: ScraperPipelineConfig | None = None,
) -> DocumentContext:
    path = Path(pdf_path)
    if config is None:
        config = ScraperPipelineConfig(
            scraper_dir=scraper_dir,
            scrape_sqlite=scrape_sqlite,
            overwrite_scrape=overwrite,
        )
    sqlite_path = prepare_scrape_sqlite(path, config=config)
    return load_scraped_document(sqlite_path, pdf_path=path, render_pages=render_pages, dpi=dpi)


def prepare_scrape_sqlite(pdf_path: str | Path, *, config: ScraperPipelineConfig) -> Path:
    path = Path(pdf_path)
    if config.scrape_sqlite is not None:
        sqlite_path = Path(config.scrape_sqlite).expanduser().resolve()
        if not sqlite_path.exists():
            raise FileNotFoundError(f"scrape.sqlite does not exist: {sqlite_path}")
    else:
        run_dir = scrape_run_dir(path, config.scraper_dir)
        sqlite_path = run_dir / "scrape.sqlite"
        if config.overwrite_scrape or not sqlite_path.exists():
            from app.services.scraper.pdf_scraper import scrape_pdf

            scrape_pdf(path, run_dir, doc_id=article_id_from_pdf_name(path.name))

    enrich_scrape_sqlite(sqlite_path, config=config)
    return sqlite_path


def enrich_scrape_sqlite(sqlite_path: str | Path, *, config: ScraperPipelineConfig) -> dict[str, Any]:
    db_path = Path(sqlite_path).expanduser().resolve()
    summary: dict[str, Any] = {"sqlite_path": str(db_path)}

    if config.run_visual:
        from app.services.scraper.visual_executor import run_visual_tasks

        summary["visual"] = run_visual_tasks(
            db_path,
            provider=config.visual_provider,
            limit=config.visual_limit,
        )

    if config.run_ocsr:
        from app.services.scraper.ocsr_executor import run_ocsr

        summary["ocsr"] = run_ocsr(
            db_path,
            provider=config.ocsr_provider,
            detector_provider=config.ocsr_detector_provider,
            limit=config.ocsr_limit,
            rerun=config.ocsr_rerun,
            batch_size=config.ocsr_batch_size,
            device=config.ocsr_device,
            min_confidence=config.ocsr_min_confidence,
        )

    if config.run_chemical_agents:
        summary["chemical_agents"] = run_chemical_agent_stage(db_path, config=config)

    return summary


def run_chemical_agent_stage(sqlite_path: str | Path, *, config: ScraperPipelineConfig) -> dict[str, Any]:
    from app.services.agent.llm import LLMConfig, load_env_file
    from app.services.agent.multi_agent_pipeline import run_multi_agent_pipeline

    db_path = Path(sqlite_path).expanduser().resolve()
    load_env_file(Path(config.chemical_env_file))
    data_config = LLMConfig.from_env(
        provider=config.chemical_llm_provider,
        model=config.chemical_data_model,
        base_url=config.chemical_llm_base_url,
        temperature=config.chemical_temperature,
        max_tokens=config.chemical_max_tokens,
        timeout_seconds=config.chemical_timeout,
        use_response_format=not config.chemical_no_response_format,
    )
    chemical_config = LLMConfig.from_env(
        provider=config.chemical_llm_provider,
        model=config.chemical_model or config.chemical_data_model,
        base_url=config.chemical_llm_base_url,
        temperature=config.chemical_temperature,
        max_tokens=config.chemical_max_tokens,
        timeout_seconds=config.chemical_timeout,
        use_response_format=not config.chemical_no_response_format,
    )
    output_dir = chemical_agent_output_dir(db_path, config.chemical_agent_dir)
    report = run_multi_agent_pipeline(
        db_path,
        output_dir,
        data_config=data_config,
        chemical_config=chemical_config,
        data_limit=config.chemical_data_limit,
        chemical_limit=config.chemical_limit,
        max_crops_per_figure=config.chemical_max_crops_per_figure,
    )
    chemical_json = Path(report["chemical_ocr_agent"]["artifacts"]["json"])
    report["sqlite_evidence_import"] = upsert_chemical_agent_evidence(db_path, chemical_json)
    return report


def chemical_agent_output_dir(sqlite_path: Path, configured_root: str | Path | None) -> Path:
    if configured_root is None:
        return sqlite_path.parent / "chemical_agents"
    return Path(configured_root).expanduser() / sqlite_path.parent.name


def upsert_chemical_agent_evidence(sqlite_path: str | Path, chemical_report_path: str | Path) -> dict[str, int]:
    db_path = Path(sqlite_path).expanduser().resolve()
    report = json.loads(Path(chemical_report_path).read_text(encoding="utf-8"))
    records = report.get("records", [])
    inserted = 0
    skipped = 0

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        for record in records:
            if not isinstance(record, dict):
                skipped += 1
                continue
            if record.get("validation_status") != "accepted":
                skipped += 1
                continue
            smiles = record.get("canonical_smiles") or record.get("smiles")
            if not isinstance(smiles, str) or not smiles.strip() or smiles == "NOT_DETECTED":
                skipped += 1
                continue
            detection = conn.execute(
                """
                SELECT *
                FROM structure_detections
                WHERE detection_id = ?
                """,
                (record.get("detection_id"),),
            ).fetchone()
            if detection is None:
                skipped += 1
                continue
            _upsert_agent_smiles_evidence(conn, detection, record, smiles.strip())
            inserted += 1
        conn.commit()
    finally:
        conn.close()

    return {"inserted": inserted, "skipped": skipped}


def _upsert_agent_smiles_evidence(
    conn: sqlite3.Connection,
    detection: sqlite3.Row,
    record: dict[str, Any],
    smiles: str,
) -> None:
    compound_id = str(record.get("compound_id") or "unknown").strip() or "unknown"
    evidence_id = f"{detection['detection_id']}:chemical_agent:{safe_evidence_suffix(compound_id)}"
    confidence = as_float(record.get("agent_confidence") or record.get("mapping_confidence"))
    metadata = {
        "source": "chemical_ocr_agent",
        "compound_id": compound_id,
        "chemical_agent_record": record,
    }
    text = (
        f"Chemical agent SMILES: compound_id={compound_id} | "
        f"smiles={record.get('smiles')} | canonical_smiles={smiles} | "
        f"validation_status={record.get('validation_status')} | "
        f"smiles_source={record.get('smiles_source')} | "
        f"mapping_confidence={record.get('mapping_confidence')} | "
        f"agent_confidence={record.get('agent_confidence')} | "
        f"mapping_evidence={record.get('mapping_evidence')} | "
        f"parent figure: {detection['parent_figure_id']} | crop: {detection['image_path']}"
    )

    conn.execute("DELETE FROM evidence_fts WHERE evidence_id = ?", (evidence_id,))
    conn.execute("DELETE FROM evidence_blocks WHERE evidence_id = ?", (evidence_id,))
    conn.execute(
        """
        INSERT INTO evidence_blocks (
          evidence_id, doc_id, file_id, page_number, source_type, section, title,
          caption, text, bbox_json, metadata_json, parser, confidence
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evidence_id,
            detection["doc_id"],
            detection["file_id"],
            detection["page_number"],
            "chemical_structure_smiles",
            None,
            detection["parent_figure_id"],
            compound_id,
            text,
            detection["bbox_json"],
            json.dumps(metadata, ensure_ascii=False),
            "chemical_ocr_agent",
            confidence,
        ),
    )
    conn.execute(
        """
        INSERT INTO evidence_fts (evidence_id, doc_id, source_type, text, caption, section)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (evidence_id, detection["doc_id"], "chemical_structure_smiles", text, compound_id, ""),
    )
    if not str(detection["smiles"] or "").strip():
        conn.execute(
            """
            UPDATE structure_detections
            SET smiles = ?, confidence = COALESCE(?, confidence)
            WHERE detection_id = ?
            """,
            (smiles, confidence, detection["detection_id"]),
        )


def scrape_run_dir(pdf_path: str | Path, scraper_dir: str | Path | None = None) -> Path:
    root = Path(scraper_dir) if scraper_dir is not None else DEFAULT_SCRAPER_DIR
    return root / article_id_from_pdf_name(Path(pdf_path).name)


def article_id_from_pdf_name(pdf_name: str) -> str:
    name = Path(pdf_name.strip()).name
    if name.lower().endswith(".pdf"):
        return name[:-4]
    return name


def load_scraped_document(
    sqlite_path: str | Path,
    *,
    pdf_path: str | Path | None = None,
    render_pages: bool = True,
    dpi: int = 160,
) -> DocumentContext:
    db_path = Path(sqlite_path)
    resolved_pdf_path = Path(pdf_path) if pdf_path is not None else source_pdf_path(db_path)
    rendered_pages = {}
    if render_pages and resolved_pdf_path.exists():
        rendered = load_pdf(resolved_pdf_path, render_pages=True, dpi=dpi)
        rendered_pages = {page.number: page.image_jpeg for page in rendered.pages}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables_by_page = load_scraped_tables(conn)
        evidence_by_page = load_scraped_evidence(conn)
        pages = []
        for row in conn.execute("SELECT page_number, text FROM pages ORDER BY page_number"):
            page_number = int(row["page_number"])
            text = compose_page_text(row["text"] or "", evidence_by_page.get(page_number, []))
            pages.append(
                PageContext(
                    number=page_number,
                    text=text,
                    tables=tables_by_page.get(page_number, []),
                    image_jpeg=rendered_pages.get(page_number),
                )
            )
    finally:
        conn.close()
    return DocumentContext(pdf_path=resolved_pdf_path, pages=pages)


def source_pdf_path(sqlite_path: Path) -> Path:
    conn = sqlite3.connect(str(sqlite_path))
    try:
        row = conn.execute("SELECT source_path FROM documents ORDER BY created_at DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    if row is None:
        return sqlite_path
    return Path(row[0])


def load_scraped_tables(conn: sqlite3.Connection) -> dict[int, list[str]]:
    tables_by_page: dict[int, list[str]] = {}
    tables = conn.execute(
        """
        SELECT table_id, page_number, label, caption, columns_json
        FROM tables
        ORDER BY page_number, label, table_id
        """
    ).fetchall()
    for table in tables:
        columns = json_list(table["columns_json"])
        rows = [
            json_list(row["cells_json"])
            for row in conn.execute(
                """
                SELECT cells_json
                FROM table_rows
                WHERE table_id = ?
                ORDER BY row_index
                """,
                (table["table_id"],),
            )
        ]
        markdown = table_to_markdown([columns, *rows])
        if not markdown:
            continue
        title = " | ".join(part for part in [table["label"], table["caption"]] if part)
        if title:
            markdown = f"{title}\n{markdown}"
        tables_by_page.setdefault(int(table["page_number"]), []).append(markdown)
    return tables_by_page


def load_scraped_evidence(conn: sqlite3.Connection) -> dict[int, list[sqlite3.Row]]:
    evidence_by_page: dict[int, list[sqlite3.Row]] = {}
    rows = conn.execute(
        """
        SELECT page_number, source_type, section, title, caption, text
        FROM evidence_blocks
        WHERE page_number IS NOT NULL
          AND source_type IN (
            'table_caption',
            'figure_caption',
            'figure_image',
            'scheme_image',
            'chemical_structure_image',
            'chemical_structure_smiles'
          )
        ORDER BY page_number, source_type, evidence_id
        """
    ).fetchall()
    for row in rows:
        evidence_by_page.setdefault(int(row["page_number"]), []).append(row)
    return evidence_by_page


def compose_page_text(page_text: str, evidence_rows: list[sqlite3.Row]) -> str:
    if not evidence_rows:
        return page_text
    evidence_lines = ["SCRAPER EVIDENCE"]
    for row in evidence_rows:
        label = " | ".join(
            str(part)
            for part in [row["source_type"], row["section"], row["title"], row["caption"]]
            if part
        )
        text = str(row["text"] or "").strip()
        evidence_lines.append(f"{label}: {text}" if label else text)
    return "\n\n".join(part for part in [page_text.strip(), "\n".join(evidence_lines)] if part)


def json_list(value: Any) -> list[str]:
    if value is None:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return [str(value)]
    if isinstance(parsed, list):
        return ["" if item is None else str(item) for item in parsed]
    return [str(parsed)]


def safe_evidence_suffix(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return cleaned.strip("_") or "compound"


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
