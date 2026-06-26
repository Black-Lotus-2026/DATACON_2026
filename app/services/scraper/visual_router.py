from __future__ import annotations

import csv
import re
from pathlib import Path

from app.services.scraper.models import FigureRecord, PageRecord, TableRecord, VisualTask


"""Route expensive visual work without executing heavy models.

This layer answers "what should we inspect visually?" based on text coverage,
table coverage, captions, and chemistry-heavy keywords. Executors can then run
only the queued tasks that matter for the current experiment.
"""


DOCKING_KEYWORDS = {
    "docking",
    "interaction",
    "interactions",
    "binding",
    "pose",
    "enzyme",
    "active site",
}
ACTIVITY_FIGURE_KEYWORDS = {
    "inhibition",
    "activity",
    "mic",
    "zone",
    "antimicrobial",
    "antibacterial",
    "antifungal",
    "graph",
}
STRUCTURE_KEYWORDS = {
    "synthesis",
    "structure",
    "structures",
    "hybrid",
    "hybrids",
    "derivatives",
}
SMILES_RE = re.compile(r"\b[A-Z][A-Za-z0-9@+\-\[\]\(\)=#$\\/]{8,}\b")
COMPOUND_ID_RE = re.compile(r"\b\d{1,3}[a-z]\b|\b\d{1,3}[a-z]-\d{1,3}[a-z]\b", re.I)


def route_visual_tasks(
    *,
    doc_id: str,
    file_id: str,
    output_dir: Path,
    pages: list[PageRecord],
    tables: list[TableRecord],
    figures: list[FigureRecord],
) -> list[VisualTask]:
    """Build a prioritized task queue for OCR, table repair, structure detection, and OCSR."""
    table_pages = {table.page_number for table in tables}
    table_row_count = sum(len(table.rows) for table in tables)
    full_text = "\n".join(page.text for page in pages)
    smiles_count = len(set(SMILES_RE.findall(full_text)))
    compound_ids_in_tables = _count_compound_ids_in_tables(tables)

    tasks: list[VisualTask] = []
    tasks.extend(_document_ocr_tasks(doc_id, file_id, pages))
    tasks.extend(_table_ocr_tasks(doc_id, file_id, pages, table_pages))
    tasks.extend(
        _figure_tasks(
            doc_id=doc_id,
            file_id=file_id,
            figures=figures,
            table_row_count=table_row_count,
            smiles_count=smiles_count,
            compound_ids_in_tables=compound_ids_in_tables,
        )
    )

    tasks = _dedupe_tasks(tasks)
    _export_visual_tasks(output_dir, tasks)
    return tasks


def _document_ocr_tasks(doc_id: str, file_id: str, pages: list[PageRecord]) -> list[VisualTask]:
    tasks: list[VisualTask] = []
    for page in pages:
        text_chars = len(page.text.strip())
        if text_chars >= 500:
            continue
        tasks.append(
            VisualTask(
                task_id=f"{doc_id}:{file_id}:p{page.page_number:04d}:document_ocr",
                doc_id=doc_id,
                file_id=file_id,
                page_number=page.page_number,
                task_type="document_ocr",
                target_type="page",
                target_id=page.page_id,
                provider_hint="surya_or_paddleocr",
                priority=90,
                reason=f"Low selectable text on page: {text_chars} characters.",
                payload={
                    "page_number": page.page_number,
                    "text_chars": text_chars,
                    "recommended_providers": ["surya", "paddleocr"],
                },
            )
        )
    return tasks


def _table_ocr_tasks(
    doc_id: str,
    file_id: str,
    pages: list[PageRecord],
    table_pages: set[int],
) -> list[VisualTask]:
    tasks: list[VisualTask] = []
    for page in pages:
        if page.page_number in table_pages:
            continue
        if "table" not in page.text.lower():
            continue
        tasks.append(
            VisualTask(
                task_id=f"{doc_id}:{file_id}:p{page.page_number:04d}:table_ocr",
                doc_id=doc_id,
                file_id=file_id,
                page_number=page.page_number,
                task_type="table_ocr",
                target_type="page",
                target_id=page.page_id,
                provider_hint="surya_table_or_paddle_structure",
                priority=75,
                reason="Page mentions a table but no structured table was recovered.",
                payload={
                    "page_number": page.page_number,
                    "recommended_providers": ["surya_table", "paddleocr_pp_structure"],
                },
            )
        )
    return tasks


def _figure_tasks(
    *,
    doc_id: str,
    file_id: str,
    figures: list[FigureRecord],
    table_row_count: int,
    smiles_count: int,
    compound_ids_in_tables: int,
) -> list[VisualTask]:
    tasks: list[VisualTask] = []
    chemical_image_dependency = compound_ids_in_tables > smiles_count or smiles_count == 0

    for figure in figures:
        caption = (figure.caption or "").lower()
        is_structure_rich = figure.kind == "scheme" or any(keyword in caption for keyword in STRUCTURE_KEYWORDS)
        needs_semantic_description = any(keyword in caption for keyword in DOCKING_KEYWORDS | ACTIVITY_FIGURE_KEYWORDS)

        if is_structure_rich:
            priority_boost = chemical_image_dependency or figure.kind == "scheme"
            tasks.append(
                VisualTask(
                    task_id=f"{figure.figure_id}:structure_detection",
                    doc_id=doc_id,
                    file_id=file_id,
                    page_number=figure.page_number,
                    task_type="chemical_structure_detection",
                    target_type="figure",
                    target_id=figure.figure_id,
                    provider_hint="structure_detector",
                    priority=85 if priority_boost else 55,
                    reason=(
                        "Figure/scheme likely contains chemical structures; structure detection can link "
                        "compound ids from text/tables to image-local structures."
                    ),
                    payload={
                        "image_path": figure.image_path,
                        "caption": figure.caption,
                        "kind": figure.kind,
                        "compound_ids_in_tables": compound_ids_in_tables,
                        "smiles_count_in_text": smiles_count,
                        "next_provider": "molscribe_or_decimer",
                    },
                )
            )
            tasks.append(
                VisualTask(
                    task_id=f"{figure.figure_id}:ocsr",
                    doc_id=doc_id,
                    file_id=file_id,
                    page_number=figure.page_number,
                    task_type="ocsr",
                    target_type="figure",
                    target_id=figure.figure_id,
                    provider_hint="molscribe_or_decimer",
                    priority=80 if priority_boost else 50,
                    reason="Chemical structure crops should be converted to structure strings after detection.",
                    payload={
                        "image_path": figure.image_path,
                        "caption": figure.caption,
                        "requires": "chemical_structure_detection",
                    },
                )
            )

        if needs_semantic_description:
            tasks.append(
                VisualTask(
                    task_id=f"{figure.figure_id}:vlm_describe",
                    doc_id=doc_id,
                    file_id=file_id,
                    page_number=figure.page_number,
                    task_type="vlm_describe",
                    target_type="figure",
                    target_id=figure.figure_id,
                    provider_hint="vlm",
                    priority=60 if table_row_count else 80,
                    reason="Caption suggests visual-only semantic information such as docking, activity, or graphs.",
                    payload={
                        "image_path": figure.image_path,
                        "caption": figure.caption,
                        "focus": ["compound labels", "measured values", "assay meaning", "visual relationships"],
                    },
                )
            )

        if figure.kind == "figure" and is_structure_rich and not chemical_image_dependency:
            tasks.append(
                VisualTask(
                    task_id=f"{figure.figure_id}:light_ocr",
                    doc_id=doc_id,
                    file_id=file_id,
                    page_number=figure.page_number,
                    task_type="image_text_ocr",
                    target_type="figure",
                    target_id=figure.figure_id,
                    provider_hint="surya_or_paddleocr",
                    priority=35,
                    reason="Structure-rich figure may contain labels, but text/table coverage is already decent.",
                    payload={
                        "image_path": figure.image_path,
                        "caption": figure.caption,
                    },
                )
            )

    return tasks


def _count_compound_ids_in_tables(tables: list[TableRecord]) -> int:
    values: set[str] = set()
    for table in tables:
        for row in table.rows:
            if not row:
                continue
            for match in COMPOUND_ID_RE.findall(row[0]):
                values.add(match.lower())
    return len(values)


def _dedupe_tasks(tasks: list[VisualTask]) -> list[VisualTask]:
    best: dict[str, VisualTask] = {}
    for task in tasks:
        current = best.get(task.task_id)
        if current is None or task.priority > current.priority:
            best[task.task_id] = task
    return sorted(best.values(), key=lambda task: (-task.priority, task.page_number or 0, task.task_id))


def _export_visual_tasks(output_dir: Path, tasks: list[VisualTask]) -> None:
    path = output_dir / "visual_tasks.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "priority",
                "task_type",
                "provider_hint",
                "page_number",
                "target_type",
                "target_id",
                "reason",
            ],
        )
        writer.writeheader()
        for task in tasks:
            writer.writerow(
                {
                    "priority": task.priority,
                    "task_type": task.task_type,
                    "provider_hint": task.provider_hint,
                    "page_number": task.page_number or "",
                    "target_type": task.target_type,
                    "target_id": task.target_id,
                    "reason": task.reason,
                }
            )
