from __future__ import annotations

import argparse
import csv
import hashlib
import re
from pathlib import Path

from app.services.scraper.models import EvidenceBlock, FigureRecord, PageRecord, ScrapeResult, TableRecord
from app.services.scraper.storage import ScrapeStore
from app.services.scraper.visual_router import route_visual_tasks


"""PDF-to-SQLite evidence scraper.

The module keeps parsing and extraction separate from final ChemX relation
extraction. Every output is stored as traceable evidence: text blocks, captions,
table rows, figure crops, and deferred visual tasks.
"""


CAPTION_RE = re.compile(
    r"^\s*(Table|Figure|Fig\.|Scheme)\s+([A-Za-z]?\d+[A-Za-z]?)\.?\s*(.+)",
    re.IGNORECASE | re.MULTILINE,
)
HEADING_RE = re.compile(r"^(abstract|introduction|results|discussion|conclusion|experimental|methods|references)\b", re.I)


def scrape_pdf(pdf_path: Path, output_dir: Path, doc_id: str | None = None) -> ScrapeResult:
    """Scrape one PDF into a run directory and a SQLite evidence database."""
    pdf_path = pdf_path.resolve()
    output_dir = output_dir.resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file, got {pdf_path.name}")

    doc_id = doc_id or _slug(pdf_path.stem)
    sqlite_path = output_dir / "scrape.sqlite"
    sha256 = _sha256(pdf_path)
    file_id = "main"

    pages, paragraph_blocks, caption_blocks = _extract_pages_and_text(pdf_path, doc_id, file_id)
    tables, row_blocks = _extract_tables(pdf_path, doc_id, file_id, caption_blocks)
    figures, figure_blocks = _extract_figures(pdf_path, output_dir, doc_id, file_id, caption_blocks)
    visual_tasks = route_visual_tasks(
        doc_id=doc_id,
        file_id=file_id,
        output_dir=output_dir,
        pages=pages,
        tables=tables,
        figures=figures,
    )
    _export_tables_csv(output_dir, tables)

    evidence = paragraph_blocks + caption_blocks + row_blocks + figure_blocks
    row_evidence = {block.evidence_id: block for block in row_blocks}
    diagnostics = {
        "pages_count": len(pages),
        "evidence_count": len(evidence),
        "tables_count": len(tables),
        "table_rows_count": sum(len(table.rows) for table in tables),
        "figures_count": len(figures),
        "ocr_blocks_count": sum(1 for figure in figures if figure.ocr_text.strip()),
        "visual_tasks_count": len(visual_tasks),
        "text_chars_count": sum(len(page.text) for page in pages),
        "notes": _diagnostic_notes(pages, tables, caption_blocks),
    }

    store = ScrapeStore(sqlite_path)
    try:
        store.reset_document(doc_id)
        store.insert_document(doc_id, pdf_path, sha256)
        store.insert_file(file_id, doc_id, "main", pdf_path, sha256)
        store.insert_pages(pages)
        store.insert_evidence(evidence)
        store.insert_tables(tables, row_evidence)
        store.insert_figures(figures)
        store.insert_visual_tasks(visual_tasks)
        store.insert_diagnostics(doc_id, diagnostics)
        store.commit()
    finally:
        store.close()

    return ScrapeResult(
        doc_id=doc_id,
        sqlite_path=str(sqlite_path),
        pages_count=diagnostics["pages_count"],
        evidence_count=diagnostics["evidence_count"],
        tables_count=diagnostics["tables_count"],
        table_rows_count=diagnostics["table_rows_count"],
        figures_count=diagnostics["figures_count"],
        ocr_blocks_count=diagnostics["ocr_blocks_count"],
        visual_tasks_count=diagnostics["visual_tasks_count"],
    )


def _extract_pages_and_text(
    pdf_path: Path,
    doc_id: str,
    file_id: str,
) -> tuple[list[PageRecord], list[EvidenceBlock], list[EvidenceBlock]]:
    """Extract selectable text first; OCR is routed later only when coverage is weak."""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required. Install dependencies with: pip install -r requirements.txt") from exc

    pages: list[PageRecord] = []
    paragraphs: list[EvidenceBlock] = []
    captions: list[EvidenceBlock] = []
    current_section: str | None = None

    with fitz.open(str(pdf_path)) as doc:
        for page_index, page in enumerate(doc, start=1):
            page_text = page.get_text("text") or ""
            pages.append(
                PageRecord(
                    page_id=f"{doc_id}:{file_id}:p{page_index:04d}",
                    doc_id=doc_id,
                    file_id=file_id,
                    page_number=page_index,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    text=page_text,
                )
            )

            blocks = page.get_text("blocks")
            block_index = 0
            for block in blocks:
                if len(block) < 5:
                    continue
                x0, y0, x1, y1, text = block[:5]
                cleaned = _clean_text(str(text))
                if len(cleaned) < 20:
                    continue

                heading = _maybe_heading(cleaned)
                if heading:
                    current_section = heading

                caption = _caption_from_text(cleaned)
                if caption:
                    source_type = "table_caption" if caption[0].lower() == "table" else "figure_caption"
                    blocks_target = captions
                else:
                    source_type = "section_heading" if heading else "paragraph"
                    blocks_target = paragraphs

                block_index += 1
                blocks_target.append(
                    EvidenceBlock(
                        evidence_id=f"{doc_id}:{file_id}:p{page_index:04d}:text:{block_index:04d}",
                        doc_id=doc_id,
                        file_id=file_id,
                        page_number=page_index,
                        source_type=source_type,
                        section=current_section,
                        title=heading,
                        caption=cleaned if caption else None,
                        text=cleaned,
                        bbox=(float(x0), float(y0), float(x1), float(y1)),
                        parser="pymupdf",
                        confidence=0.75,
                    )
                )

    return pages, paragraphs, captions


def _extract_tables(
    pdf_path: Path,
    doc_id: str,
    file_id: str,
    caption_blocks: list[EvidenceBlock],
) -> tuple[list[TableRecord], list[EvidenceBlock]]:
    layout_tables = _extract_layout_tables(pdf_path, doc_id, file_id)
    layout_pages = {table.page_number for table in layout_tables}
    fallback_tables = _extract_pdfplumber_tables(pdf_path, doc_id, file_id, caption_blocks, skip_pages=layout_pages)
    tables = _dedupe_tables(layout_tables + fallback_tables)
    return tables, _build_table_row_evidence(tables)


def _extract_layout_tables(pdf_path: Path, doc_id: str, file_id: str) -> list[TableRecord]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required. Install dependencies with: pip install -r requirements.txt") from exc

    tables: list[TableRecord] = []
    seen: set[tuple[int, str]] = set()

    with fitz.open(str(pdf_path)) as doc:
        for page_index, page in enumerate(doc, start=1):
            blocks = [block for block in page.get_text("dict").get("blocks", []) if block.get("type") == 0]
            for block_index, block in enumerate(blocks):
                text = _block_text(block)
                caption = _caption_from_text(text)
                if not caption or caption[0].lower() != "table":
                    continue

                label = f"Table {caption[1]}"
                dedupe_key = (page_index, label.lower())
                if dedupe_key in seen:
                    continue

                candidate_blocks = _blocks_after_table_caption(blocks, block_index)
                columns, rows, bbox = _table_from_layout_blocks(candidate_blocks)
                if len(columns) < 2 or not rows:
                    continue

                seen.add(dedupe_key)
                table_id = f"{doc_id}:{file_id}:p{page_index:04d}:layout_table:{_slug(label.lower())}"
                tables.append(
                    TableRecord(
                        table_id=table_id,
                        doc_id=doc_id,
                        file_id=file_id,
                        page_number=page_index,
                        label=label,
                        caption=_clean_text(text),
                        columns=columns,
                        rows=rows,
                        bbox=bbox,
                        parser="pymupdf_layout",
                        confidence=0.86,
                    )
                )

    return tables


def _extract_pdfplumber_tables(
    pdf_path: Path,
    doc_id: str,
    file_id: str,
    caption_blocks: list[EvidenceBlock],
    *,
    skip_pages: set[int],
) -> list[TableRecord]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber is required. Install dependencies with: pip install -r requirements.txt") from exc

    captions_by_page = _captions_by_page(caption_blocks)
    tables: list[TableRecord] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            if page_index in skip_pages:
                continue
            extracted = page.extract_tables() or []
            for table_index, raw_table in enumerate(extracted, start=1):
                rows = _normalize_table(raw_table)
                if len(rows) < 2:
                    continue

                columns = rows[0]
                data_rows = rows[1:]
                label, caption = _nearest_table_caption(captions_by_page.get(page_index, []), table_index)
                table_id = f"{doc_id}:{file_id}:p{page_index:04d}:table:{table_index:03d}"
                table = TableRecord(
                    table_id=table_id,
                    doc_id=doc_id,
                    file_id=file_id,
                    page_number=page_index,
                    label=label or f"Table {table_index}",
                    caption=caption,
                    columns=columns,
                    rows=data_rows,
                    bbox=None,
                    parser="pdfplumber",
                    confidence=0.7,
                )
                tables.append(table)

    return tables


def _build_table_row_evidence(tables: list[TableRecord]) -> list[EvidenceBlock]:
    row_blocks: list[EvidenceBlock] = []
    for table in tables:
        for row_index, row in enumerate(table.rows, start=1):
            row_blocks.append(
                EvidenceBlock(
                    evidence_id=f"{table.table_id}:row:{row_index:04d}",
                    doc_id=table.doc_id,
                    file_id=table.file_id,
                    page_number=table.page_number,
                    source_type="table_row",
                    section=None,
                    title=table.label,
                    caption=table.caption,
                    text=_row_to_text(table.label, table.caption, table.columns, row),
                    bbox=table.bbox,
                    parser=table.parser,
                    confidence=table.confidence,
                    metadata={"table_id": table.table_id, "row_index": row_index},
                )
            )
    return row_blocks


def _extract_figures(
    pdf_path: Path,
    output_dir: Path,
    doc_id: str,
    file_id: str,
    caption_blocks: list[EvidenceBlock],
) -> tuple[list[FigureRecord], list[EvidenceBlock]]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required. Install dependencies with: pip install -r requirements.txt") from exc

    figures_dir = output_dir / "images" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    for old_png in figures_dir.glob("*.png"):
        old_png.unlink()

    figure_captions = [
        block
        for block in caption_blocks
        if block.source_type == "figure_caption" and block.page_number is not None and block.bbox is not None
    ]
    figure_captions.sort(key=lambda block: (block.page_number or 0, block.bbox[1] if block.bbox else 0))

    figures: list[FigureRecord] = []
    seen: set[tuple[int, str, str]] = set()
    with fitz.open(str(pdf_path)) as doc:
        for index, block in enumerate(figure_captions, start=1):
            page = doc[(block.page_number or 1) - 1]
            parsed = _caption_from_text(block.text)
            if not parsed:
                continue

            kind = _figure_kind(parsed[0])
            label = f"{parsed[0].title().replace('Fig.', 'Figure')} {parsed[1]}"
            dedupe_key = (block.page_number or 0, kind, label.lower())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            crop_bbox = _guess_figure_bbox(page.rect, block.bbox)
            if not crop_bbox:
                continue

            image_name = f"{index:03d}_p{block.page_number:04d}_{_slug(label)}.png"
            image_path = figures_dir / image_name
            matrix = fitz.Matrix(2, 2)
            pixmap = page.get_pixmap(matrix=matrix, clip=fitz.Rect(crop_bbox), alpha=False)
            pixmap.save(str(image_path))

            figure_id = f"{doc_id}:{file_id}:p{block.page_number:04d}:{kind}:{_slug(label.lower())}"
            figures.append(
                FigureRecord(
                    figure_id=figure_id,
                    doc_id=doc_id,
                    file_id=file_id,
                    page_number=block.page_number or 0,
                    label=label,
                    caption=block.text,
                    image_path=str(image_path),
                    bbox=crop_bbox,
                    kind=kind,
                    ocr_text="",
                    parser="pymupdf_render",
                    confidence=0.65,
                )
            )

    return figures, _build_figure_evidence(figures)


def _build_figure_evidence(figures: list[FigureRecord]) -> list[EvidenceBlock]:
    blocks: list[EvidenceBlock] = []
    for figure in figures:
        text_parts = [
            figure.label or figure.kind,
            figure.caption or "",
            f"image_path: {figure.image_path}",
        ]
        if figure.ocr_text.strip():
            text_parts.append(f"ocr: {figure.ocr_text.strip()}")
        blocks.append(
            EvidenceBlock(
                evidence_id=f"{figure.figure_id}:image",
                doc_id=figure.doc_id,
                file_id=figure.file_id,
                page_number=figure.page_number,
                source_type=f"{figure.kind}_image",
                title=figure.label,
                caption=figure.caption,
                text=" | ".join(part for part in text_parts if part),
                bbox=figure.bbox,
                parser=figure.parser,
                confidence=figure.confidence,
                metadata={"figure_id": figure.figure_id, "image_path": figure.image_path},
            )
        )
    return blocks


def _figure_kind(label: str) -> str:
    lowered = label.lower()
    if lowered.startswith("scheme"):
        return "scheme"
    return "figure"


def _guess_figure_bbox(page_rect, caption_bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float] | None:
    margin = 18.0
    caption_top = caption_bbox[1]
    y1 = max(0.0, caption_top - 6.0)
    y0 = max(0.0, y1 - 330.0)
    x0 = max(0.0, min(caption_bbox[0] - margin, 40.0))
    x1 = min(float(page_rect.width), max(caption_bbox[2] + margin, float(page_rect.width) - 40.0))

    if y1 - y0 < 40 or x1 - x0 < 80:
        return None
    return (x0, y0, x1, y1)


def _blocks_after_table_caption(blocks: list[dict], caption_index: int) -> list[dict]:
    selected: list[dict] = []
    has_data = False
    for block in blocks[caption_index + 1 :]:
        text = _block_text(block)
        lowered = text.lower()
        if "for peer review" in lowered:
            break
        if _caption_from_text(text) and selected:
            break
        if has_data and _looks_like_body_paragraph(block):
            break
        selected.append(block)
        has_data = has_data or _block_has_table_data(block)
    return selected


def _table_from_layout_blocks(blocks: list[dict]) -> tuple[list[str], list[list[str]], tuple[float, float, float, float] | None]:
    lines = _layout_lines(blocks)
    if not lines:
        return [], [], None

    first_data_index = None
    for index, line in enumerate(lines):
        if _looks_like_table_data_line(line):
            first_data_index = index
            break
    if first_data_index is None:
        return [], [], None

    data_lines = []
    expected_width = None
    for line in lines[first_data_index:]:
        if not _looks_like_table_data_line(line):
            if data_lines:
                break
            continue
        cells = [_clean_cell(span["text"]) for span in line["spans"]]
        if expected_width is None:
            expected_width = len(cells)
        if len(cells) != expected_width:
            break
        data_lines.append(line)

    if not data_lines:
        return [], [], None

    columns = _infer_columns(lines[:first_data_index], data_lines)
    rows = [[_clean_cell(span["text"]) for span in line["spans"]] for line in data_lines]
    bbox = _bbox_for_lines(lines[: first_data_index + len(data_lines)])
    return columns, rows, bbox


def _layout_lines(blocks: list[dict]) -> list[dict]:
    spans: list[dict] = []
    for block in blocks:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = _clean_cell(span.get("text"))
                if text:
                    spans.append(
                        {
                            "text": text,
                            "x0": float(span["bbox"][0]),
                            "y0": float(span["bbox"][1]),
                            "x1": float(span["bbox"][2]),
                            "y1": float(span["bbox"][3]),
                        }
                    )
    spans.sort(key=lambda span: (span["y0"], span["x0"]))

    lines: list[dict] = []
    for span in spans:
        target = None
        for line in lines:
            if abs(line["y0"] - span["y0"]) <= 4.0:
                target = line
                break
        if target is None:
            target = {"y0": span["y0"], "spans": []}
            lines.append(target)
        target["spans"].append(span)

    for line in lines:
        line["spans"].sort(key=lambda span: span["x0"])
        line["spans"] = _merge_adjacent_spans(line["spans"])
        line["bbox"] = _bbox_for_spans(line["spans"])
    return lines


def _merge_adjacent_spans(spans: list[dict]) -> list[dict]:
    if not spans:
        return []

    merged: list[dict] = [dict(spans[0])]
    for span in spans[1:]:
        previous = merged[-1]
        gap = span["x0"] - previous["x1"]
        if gap <= 2.0:
            previous["text"] = _join_span_text(previous["text"], span["text"])
            previous["x1"] = span["x1"]
            previous["y0"] = min(previous["y0"], span["y0"])
            previous["y1"] = max(previous["y1"], span["y1"])
        else:
            merged.append(dict(span))
    return merged


def _join_span_text(left: str, right: str) -> str:
    if right in {".", ",", ":", ";", ")"}:
        return left + right
    if left.endswith(("(", "/", "-")):
        return left + right
    return f"{left} {right}"


def _block_has_table_data(block: dict) -> bool:
    return any(_looks_like_table_data_line(line) for line in _layout_lines([block]))


def _looks_like_table_data_line(line: dict) -> bool:
    spans = line["spans"]
    if len(spans) < 3:
        return False
    if not _is_row_label(spans[0]["text"]):
        return False
    return sum(1 for span in spans[1:] if _is_table_value(span["text"])) >= 2


def _is_row_label(text: str) -> bool:
    text = _clean_cell(text).strip("- ")
    if not text:
        return False
    if re.match(r"^\d+[A-Za-z]?$", text):
        return True
    if re.match(r"^[A-Za-z]{1,4}\d+[A-Za-z]?$", text):
        return True
    if re.match(r"^[A-Z][A-Za-zﬂ-]{4,30}$", text):
        return True
    return False


def _is_table_value(text: str) -> bool:
    text = _clean_cell(text)
    if text == "-":
        return True
    if re.search(r"\d", text):
        return True
    return False


def _infer_columns(header_lines: list[dict], data_lines: list[dict]) -> list[str]:
    first_row = data_lines[0]["spans"]
    column_x = [span["x0"] for span in first_row]
    columns = [""] * len(column_x)

    for line in header_lines:
        for span in line["spans"]:
            text = _clean_cell(span["text"])
            if not text or _is_table_super_header(text):
                continue
            nearest_index = min(range(len(column_x)), key=lambda index: abs(column_x[index] - span["x0"]))
            columns[nearest_index] = f"{columns[nearest_index]} {text}".strip()

    if not columns[0]:
        columns[0] = "compound"
    for index, column in enumerate(columns):
        columns[index] = column or f"column_{index + 1}"
    return _repair_columns(columns)


def _repair_columns(columns: list[str]) -> list[str]:
    repaired = columns[:]
    for index, column in enumerate(repaired[:-1]):
        if " A. niger" in column and repaired[index + 1].startswith("column_"):
            repaired[index] = column.replace(" A. niger", "").strip()
            repaired[index + 1] = "A. niger"
    return repaired


def _is_table_super_header(text: str) -> bool:
    lowered = text.lower()
    return len(text) > 32 or "inhibition zone" in lowered or "diffusion method" in lowered


def _bbox_for_lines(lines: list[dict]) -> tuple[float, float, float, float] | None:
    spans = [span for line in lines for span in line["spans"]]
    return _bbox_for_spans(spans)


def _bbox_for_spans(spans: list[dict]) -> tuple[float, float, float, float] | None:
    if not spans:
        return None
    return (
        min(span["x0"] for span in spans),
        min(span["y0"] for span in spans),
        max(span["x1"] for span in spans),
        max(span["y1"] for span in spans),
    )


def _block_text(block: dict) -> str:
    lines = []
    for line in block.get("lines", []):
        lines.append("".join(span.get("text", "") for span in line.get("spans", [])))
    return _clean_text("\n".join(lines))


def _looks_like_body_paragraph(block: dict) -> bool:
    lines = block.get("lines", [])
    if not lines:
        return False
    text = _block_text(block)
    if len(text) < 90:
        return False
    first_line_spans = lines[0].get("spans", [])
    return len(first_line_spans) <= 3 and not _caption_from_text(text)


def _dedupe_tables(tables: list[TableRecord]) -> list[TableRecord]:
    best: dict[tuple[int, str], TableRecord] = {}
    for table in tables:
        key = (table.page_number, (table.label or table.table_id).lower())
        current = best.get(key)
        if current is None or _table_score(table) > _table_score(current):
            best[key] = table
    return list(best.values())


def _table_score(table: TableRecord) -> float:
    filled = sum(1 for row in table.rows for cell in row if cell)
    return len(table.rows) * max(1, len(table.columns)) + filled / 100 + (0.2 if table.parser == "pymupdf_layout" else 0)


def _normalize_table(raw_table: list[list[str | None]]) -> list[list[str]]:
    normalized: list[list[str]] = []
    max_width = max((len(row) for row in raw_table if row), default=0)
    for row in raw_table:
        if not row:
            continue
        cells = [_clean_cell(cell) for cell in row]
        cells.extend([""] * (max_width - len(cells)))
        if any(cells):
            normalized.append(cells)
    return normalized


def _export_tables_csv(output_dir: Path, tables: list[TableRecord]) -> None:
    tables_dir = output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    for old_csv in tables_dir.glob("table_*.csv"):
        old_csv.unlink()

    for index, table in enumerate(tables, start=1):
        label = _slug(table.label or f"table_{index:03d}")
        csv_path = tables_dir / f"table_{index:03d}_p{table.page_number:04d}_{label}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(table.columns)
            writer.writerows(table.rows)


def _row_to_text(label: str | None, caption: str | None, columns: list[str], row: list[str]) -> str:
    pairs = []
    for index, value in enumerate(row):
        if not value:
            continue
        column = columns[index] if index < len(columns) and columns[index] else f"column_{index + 1}"
        pairs.append(f"{column}: {value}")
    prefix = " | ".join(part for part in [label, caption] if part)
    body = " | ".join(pairs)
    return f"{prefix} | {body}" if prefix else body


def _caption_from_text(text: str) -> tuple[str, str, str] | None:
    match = CAPTION_RE.search(text)
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)


def _captions_by_page(caption_blocks: list[EvidenceBlock]) -> dict[int, list[EvidenceBlock]]:
    by_page: dict[int, list[EvidenceBlock]] = {}
    for block in caption_blocks:
        if block.page_number is None:
            continue
        by_page.setdefault(block.page_number, []).append(block)
    return by_page


def _nearest_table_caption(captions: list[EvidenceBlock], table_index: int) -> tuple[str | None, str | None]:
    table_captions = [block for block in captions if block.source_type == "table_caption"]
    if table_captions:
        block = table_captions[min(table_index - 1, len(table_captions) - 1)]
        label = None
        parsed = _caption_from_text(block.text)
        if parsed:
            label = f"{parsed[0].title()} {parsed[1]}"
        return label, block.text
    return None, None


def _maybe_heading(text: str) -> str | None:
    first_line = text.splitlines()[0].strip()
    if len(first_line) > 80:
        return None
    if HEADING_RE.search(first_line):
        return first_line
    numbered = re.match(r"^\d+\.?\s+[A-Z][A-Za-z ,:-]{3,60}$", first_line)
    return first_line if numbered else None


def _diagnostic_notes(
    pages: list[PageRecord],
    tables: list[TableRecord],
    captions: list[EvidenceBlock],
) -> list[str]:
    notes = []
    empty_pages = [page.page_number for page in pages if len(page.text.strip()) < 50]
    if empty_pages:
        notes.append(f"Pages with little selectable text: {empty_pages[:20]}")
    if not tables:
        notes.append("No tables extracted by pdfplumber.")
    table_captions = [block for block in captions if block.source_type == "table_caption"]
    if tables and not table_captions:
        notes.append("Tables were found, but no table captions were linked.")
    return notes


def _clean_text(text: str) -> str:
    text = _normalize_pdf_text(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _clean_cell(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", _normalize_pdf_text(value)).strip()


def _normalize_pdf_text(text: str) -> str:
    replacements = {
        "\x00": " ",
        "ﬂ": "fl",
        "ﬁ": "fi",
        "−": "-",
        "–": "-",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return slug or "document"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape a PDF into a SQLite evidence store.")
    parser.add_argument("pdf", type=Path, help="Path to a PDF file.")
    parser.add_argument("--out", type=Path, default=Path("runs/scrape-dev"), help="Output directory.")
    parser.add_argument("--doc-id", default=None, help="Stable document id. Defaults to PDF stem.")
    args = parser.parse_args()

    result = scrape_pdf(args.pdf, args.out, args.doc_id)
    print(f"doc_id={result.doc_id}")
    print(f"sqlite={result.sqlite_path}")
    print(f"pages={result.pages_count}")
    print(f"evidence_blocks={result.evidence_count}")
    print(f"tables={result.tables_count}")
    print(f"table_rows={result.table_rows_count}")
    print(f"figures={result.figures_count}")
    print(f"visual_tasks={result.visual_tasks_count}")


if __name__ == "__main__":
    main()
