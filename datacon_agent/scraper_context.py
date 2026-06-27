from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from datacon_agent.pdf import DocumentContext, PageContext, load_pdf, table_to_markdown


DEFAULT_SCRAPER_DIR = Path("runs/datacon_agent_scrapes")


def scrape_pdf_to_document(
    pdf_path: str | Path,
    *,
    scraper_dir: str | Path | None = None,
    overwrite: bool = False,
    render_pages: bool = True,
    dpi: int = 160,
) -> DocumentContext:
    path = Path(pdf_path)
    run_dir = scrape_run_dir(path, scraper_dir)
    sqlite_path = run_dir / "scrape.sqlite"
    if overwrite or not sqlite_path.exists():
        from app.services.scraper.pdf_scraper import scrape_pdf

        scrape_pdf(path, run_dir, doc_id=article_id_from_pdf_name(path.name))
    return load_scraped_document(sqlite_path, pdf_path=path, render_pages=render_pages, dpi=dpi)


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
