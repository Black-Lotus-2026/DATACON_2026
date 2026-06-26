from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.services.scraper.models import EvidenceBlock, FigureRecord, PageRecord, TableRecord, VisualTask


"""SQLite persistence for scraper evidence.

The schema is deliberately denormalized around evidence blocks: downstream RAG
should be able to retrieve a paragraph, table row, crop, or SMILES with enough
metadata to trace it back to the original PDF page.
"""


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS files (
  file_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  mime_type TEXT,
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);

CREATE TABLE IF NOT EXISTS pages (
  page_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  page_number INTEGER NOT NULL,
  width REAL,
  height REAL,
  text TEXT,
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id),
  FOREIGN KEY (file_id) REFERENCES files(file_id)
);

CREATE TABLE IF NOT EXISTS evidence_blocks (
  evidence_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  page_number INTEGER,
  source_type TEXT NOT NULL,
  section TEXT,
  title TEXT,
  caption TEXT,
  text TEXT NOT NULL,
  bbox_json TEXT,
  metadata_json TEXT,
  parser TEXT,
  confidence REAL,
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id),
  FOREIGN KEY (file_id) REFERENCES files(file_id)
);

CREATE TABLE IF NOT EXISTS tables (
  table_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  page_number INTEGER,
  label TEXT,
  caption TEXT,
  columns_json TEXT,
  bbox_json TEXT,
  parser TEXT,
  confidence REAL,
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id),
  FOREIGN KEY (file_id) REFERENCES files(file_id)
);

CREATE TABLE IF NOT EXISTS table_rows (
  row_id TEXT PRIMARY KEY,
  table_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  row_index INTEGER NOT NULL,
  cells_json TEXT NOT NULL,
  normalized_text TEXT NOT NULL,
  FOREIGN KEY (table_id) REFERENCES tables(table_id),
  FOREIGN KEY (evidence_id) REFERENCES evidence_blocks(evidence_id)
);

CREATE TABLE IF NOT EXISTS figures (
  figure_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  page_number INTEGER,
  label TEXT,
  caption TEXT,
  image_path TEXT NOT NULL,
  bbox_json TEXT,
  kind TEXT,
  ocr_text TEXT,
  parser TEXT,
  confidence REAL,
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id),
  FOREIGN KEY (file_id) REFERENCES files(file_id)
);

CREATE TABLE IF NOT EXISTS visual_tasks (
  task_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  page_number INTEGER,
  task_type TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  provider_hint TEXT NOT NULL,
  priority INTEGER NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id),
  FOREIGN KEY (file_id) REFERENCES files(file_id)
);

CREATE TABLE IF NOT EXISTS ocr_blocks (
  ocr_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  doc_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  page_number INTEGER,
  text TEXT NOT NULL,
  bbox_json TEXT,
  provider TEXT NOT NULL,
  confidence REAL,
  metadata_json TEXT NOT NULL,
  FOREIGN KEY (task_id) REFERENCES visual_tasks(task_id),
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id),
  FOREIGN KEY (file_id) REFERENCES files(file_id)
);

CREATE TABLE IF NOT EXISTS structure_detections (
  detection_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  doc_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  page_number INTEGER,
  parent_figure_id TEXT,
  image_path TEXT NOT NULL,
  bbox_json TEXT,
  label_nearby TEXT,
  smiles TEXT,
  provider TEXT,
  confidence REAL,
  metadata_json TEXT NOT NULL,
  FOREIGN KEY (task_id) REFERENCES visual_tasks(task_id),
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id),
  FOREIGN KEY (file_id) REFERENCES files(file_id)
);

CREATE TABLE IF NOT EXISTS diagnostics (
  doc_id TEXT PRIMARY KEY,
  pages_count INTEGER NOT NULL,
  evidence_count INTEGER NOT NULL,
  tables_count INTEGER NOT NULL,
  table_rows_count INTEGER NOT NULL,
  text_chars_count INTEGER NOT NULL,
  notes_json TEXT NOT NULL,
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts
USING fts5(evidence_id UNINDEXED, doc_id UNINDEXED, source_type UNINDEXED, text, caption, section);
"""


class ScrapeStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA_SQL)

    def close(self) -> None:
        self.conn.close()

    def reset_document(self, doc_id: str) -> None:
        self.conn.execute(
            """
            DELETE FROM table_rows
            WHERE table_id IN (SELECT table_id FROM tables WHERE doc_id = ?)
               OR evidence_id IN (SELECT evidence_id FROM evidence_blocks WHERE doc_id = ?)
            """,
            (doc_id, doc_id),
        )
        for table in [
            "evidence_fts",
            "structure_detections",
            "ocr_blocks",
            "visual_tasks",
            "figures",
            "tables",
            "evidence_blocks",
            "pages",
            "files",
            "diagnostics",
            "documents",
        ]:
            self.conn.execute(f"DELETE FROM {table} WHERE doc_id = ?", (doc_id,))
        self.conn.commit()

    def insert_document(self, doc_id: str, source_path: Path, sha256: str) -> None:
        self.conn.execute(
            "INSERT INTO documents (doc_id, source_path, sha256) VALUES (?, ?, ?)",
            (doc_id, str(source_path), sha256),
        )

    def insert_file(self, file_id: str, doc_id: str, kind: str, path: Path, sha256: str) -> None:
        self.conn.execute(
            """
            INSERT INTO files (file_id, doc_id, kind, path, sha256, mime_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_id, doc_id, kind, str(path), sha256, "application/pdf"),
        )

    def insert_pages(self, pages: list[PageRecord]) -> None:
        self.conn.executemany(
            """
            INSERT INTO pages (page_id, doc_id, file_id, page_number, width, height, text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    page.page_id,
                    page.doc_id,
                    page.file_id,
                    page.page_number,
                    page.width,
                    page.height,
                    page.text,
                )
                for page in pages
            ],
        )

    def insert_evidence(self, blocks: list[EvidenceBlock]) -> None:
        rows = []
        fts_rows = []
        for block in blocks:
            bbox_json = json.dumps(block.bbox) if block.bbox else None
            metadata_json = json.dumps(block.metadata, ensure_ascii=False)
            rows.append(
                (
                    block.evidence_id,
                    block.doc_id,
                    block.file_id,
                    block.page_number,
                    block.source_type,
                    block.section,
                    block.title,
                    block.caption,
                    block.text,
                    bbox_json,
                    metadata_json,
                    block.parser,
                    block.confidence,
                )
            )
            fts_rows.append(
                (
                    block.evidence_id,
                    block.doc_id,
                    block.source_type,
                    block.text,
                    block.caption or "",
                    block.section or "",
                )
            )

        self.conn.executemany(
            """
            INSERT INTO evidence_blocks (
              evidence_id, doc_id, file_id, page_number, source_type, section, title,
              caption, text, bbox_json, metadata_json, parser, confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.conn.executemany(
            """
            INSERT INTO evidence_fts (evidence_id, doc_id, source_type, text, caption, section)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            fts_rows,
        )

    def insert_tables(self, tables: list[TableRecord], row_evidence: dict[str, EvidenceBlock]) -> None:
        table_rows = []
        for table in tables:
            self.conn.execute(
                """
                INSERT INTO tables (
                  table_id, doc_id, file_id, page_number, label, caption, columns_json,
                  bbox_json, parser, confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    table.table_id,
                    table.doc_id,
                    table.file_id,
                    table.page_number,
                    table.label,
                    table.caption,
                    json.dumps(table.columns, ensure_ascii=False),
                    json.dumps(table.bbox) if table.bbox else None,
                    table.parser,
                    table.confidence,
                ),
            )

            for index, row in enumerate(table.rows, start=1):
                evidence_id = f"{table.table_id}:row:{index:04d}"
                if evidence_id not in row_evidence:
                    continue
                table_rows.append(
                    (
                        evidence_id,
                        table.table_id,
                        evidence_id,
                        index,
                        json.dumps(row, ensure_ascii=False),
                        row_evidence[evidence_id].text,
                    )
                )

        self.conn.executemany(
            """
            INSERT INTO table_rows (
              row_id, table_id, evidence_id, row_index, cells_json, normalized_text
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            table_rows,
        )

    def insert_figures(self, figures: list[FigureRecord]) -> None:
        self.conn.executemany(
            """
            INSERT INTO figures (
              figure_id, doc_id, file_id, page_number, label, caption, image_path,
              bbox_json, kind, ocr_text, parser, confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    figure.figure_id,
                    figure.doc_id,
                    figure.file_id,
                    figure.page_number,
                    figure.label,
                    figure.caption,
                    figure.image_path,
                    json.dumps(figure.bbox) if figure.bbox else None,
                    figure.kind,
                    figure.ocr_text,
                    figure.parser,
                    figure.confidence,
                )
                for figure in figures
            ],
        )

    def insert_visual_tasks(self, tasks: list[VisualTask]) -> None:
        self.conn.executemany(
            """
            INSERT INTO visual_tasks (
              task_id, doc_id, file_id, page_number, task_type, target_type,
              target_id, provider_hint, priority, reason, status, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    task.task_id,
                    task.doc_id,
                    task.file_id,
                    task.page_number,
                    task.task_type,
                    task.target_type,
                    task.target_id,
                    task.provider_hint,
                    task.priority,
                    task.reason,
                    task.status,
                    json.dumps(task.payload, ensure_ascii=False),
                )
                for task in tasks
            ],
        )

    def insert_diagnostics(self, doc_id: str, diagnostics: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO diagnostics (
              doc_id, pages_count, evidence_count, tables_count, table_rows_count,
              text_chars_count, notes_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id,
                diagnostics["pages_count"],
                diagnostics["evidence_count"],
                diagnostics["tables_count"],
                diagnostics["table_rows_count"],
                diagnostics["text_chars_count"],
                json.dumps(diagnostics.get("notes", []), ensure_ascii=False),
            ),
        )

    def commit(self) -> None:
        self.conn.commit()
