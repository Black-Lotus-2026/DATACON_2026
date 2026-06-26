from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class PageRecord:
    page_id: str
    doc_id: str
    file_id: str
    page_number: int
    width: float
    height: float
    text: str


@dataclass(frozen=True)
class EvidenceBlock:
    evidence_id: str
    doc_id: str
    file_id: str
    page_number: int | None
    source_type: str
    text: str
    section: str | None = None
    title: str | None = None
    caption: str | None = None
    bbox: BBox | None = None
    parser: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TableRecord:
    table_id: str
    doc_id: str
    file_id: str
    page_number: int
    label: str | None
    caption: str | None
    columns: list[str]
    rows: list[list[str]]
    bbox: BBox | None = None
    parser: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class FigureRecord:
    figure_id: str
    doc_id: str
    file_id: str
    page_number: int
    label: str | None
    caption: str | None
    image_path: str
    bbox: BBox | None = None
    kind: str = "figure"
    ocr_text: str = ""
    parser: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class VisualTask:
    task_id: str
    doc_id: str
    file_id: str
    page_number: int | None
    task_type: str
    target_type: str
    target_id: str
    provider_hint: str
    priority: int
    reason: str
    status: str = "pending"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScrapeResult:
    doc_id: str
    sqlite_path: str
    pages_count: int
    evidence_count: int
    tables_count: int
    table_rows_count: int
    figures_count: int = 0
    ocr_blocks_count: int = 0
    visual_tasks_count: int = 0
