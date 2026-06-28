import sqlite3
from pathlib import Path

from app.services.scraper.storage import SCHEMA_SQL
from datacon_agent.scraper_context import (
    article_id_from_pdf_name,
    load_scraped_document,
    scrape_run_dir,
    upsert_chemical_agent_evidence,
)


def test_scraper_context_preserves_dotted_article_ids() -> None:
    assert article_id_from_pdf_name("THNO.19257.pdf") == "THNO.19257"
    assert scrape_run_dir("THNO.19257.pdf", "runs/scrapes") == Path("runs/scrapes/THNO.19257")


def test_load_scraped_document_uses_tables_and_evidence(tmp_path: Path) -> None:
    db_path = tmp_path / "scrape.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT INTO documents (doc_id, source_path, sha256) VALUES (?, ?, ?)",
            ("doc", str(tmp_path / "paper.pdf"), "sha"),
        )
        conn.execute(
            "INSERT INTO files (file_id, doc_id, kind, path, sha256) VALUES (?, ?, ?, ?, ?)",
            ("main", "doc", "pdf", str(tmp_path / "paper.pdf"), "sha"),
        )
        conn.execute(
            """
            INSERT INTO pages (page_id, doc_id, file_id, page_number, width, height, text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("doc:main:p0001", "doc", "main", 1, 100.0, 100.0, "Page text"),
        )
        conn.execute(
            """
            INSERT INTO evidence_blocks (
              evidence_id, doc_id, file_id, page_number, source_type, text, caption
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc:main:p0001:table:row:0001",
                "doc",
                "main",
                1,
                "table_row",
                "Table 1 | Km: 0.2 mM",
                "Kinetic constants",
            ),
        )
        conn.execute(
            """
            INSERT INTO evidence_blocks (
              evidence_id, doc_id, file_id, page_number, source_type, text, caption
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc:main:p0001:table:caption:0001",
                "doc",
                "main",
                1,
                "table_caption",
                "Table 1. Kinetic constants.",
                "Kinetic constants",
            ),
        )
        conn.execute(
            """
            INSERT INTO tables (
              table_id, doc_id, file_id, page_number, label, caption, columns_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("table1", "doc", "main", 1, "Table 1", "Kinetic constants", '["material", "Km"]'),
        )
        conn.execute(
            """
            INSERT INTO table_rows (row_id, table_id, evidence_id, row_index, cells_json, normalized_text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "row1",
                "table1",
                "doc:main:p0001:table:row:0001",
                1,
                '["CeO2", "0.2 mM"]',
                "material: CeO2 | Km: 0.2 mM",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    document = load_scraped_document(db_path, pdf_path=tmp_path / "paper.pdf", render_pages=False)

    assert document.pages[0].number == 1
    assert "SCRAPER EVIDENCE" in document.pages[0].text
    assert "Table 1. Kinetic constants." in document.pages[0].text
    assert "Kinetic constants" in document.pages[0].tables[0]
    assert "| CeO2 | 0.2 mM |" in document.pages[0].tables[0]


def test_upsert_chemical_agent_evidence_adds_smiles_context(tmp_path: Path) -> None:
    db_path = tmp_path / "scrape.sqlite"
    detection_id = "doc:main:p0001:scheme:scheme_1:structure_detection:det:0001"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT INTO documents (doc_id, source_path, sha256) VALUES (?, ?, ?)",
            ("doc", str(tmp_path / "paper.pdf"), "sha"),
        )
        conn.execute(
            "INSERT INTO files (file_id, doc_id, kind, path, sha256) VALUES (?, ?, ?, ?, ?)",
            ("main", "doc", "pdf", str(tmp_path / "paper.pdf"), "sha"),
        )
        conn.execute(
            """
            INSERT INTO pages (page_id, doc_id, file_id, page_number, width, height, text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("doc:main:p0001", "doc", "main", 1, 100.0, 100.0, "Page text"),
        )
        conn.execute(
            """
            INSERT INTO visual_tasks (
              task_id, doc_id, file_id, page_number, task_type, target_type,
              target_id, provider_hint, priority, reason, status, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc:main:p0001:scheme:scheme_1:structure_detection",
                "doc",
                "main",
                1,
                "chemical_structure_detection",
                "figure",
                "doc:main:p0001:scheme:scheme_1",
                "decimer",
                100,
                "fixture",
                "completed",
                "{}",
            ),
        )
        conn.execute(
            """
            INSERT INTO structure_detections (
              detection_id, task_id, doc_id, file_id, page_number,
              parent_figure_id, image_path, bbox_json, label_nearby,
              smiles, provider, confidence, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                detection_id,
                "doc:main:p0001:scheme:scheme_1:structure_detection",
                "doc",
                "main",
                1,
                "doc:main:p0001:scheme:scheme_1",
                str(tmp_path / "crop.png"),
                "[1, 1, 50, 50]",
                None,
                None,
                "decimer_segmentation",
                0.82,
                "{}",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    report_path = tmp_path / "chemical_ocr_results.json"
    report_path.write_text(
        """
        {
          "records": [
            {
              "compound_id": "6a",
              "detection_id": "doc:main:p0001:scheme:scheme_1:structure_detection:det:0001",
              "smiles": "COC(=O)Nc1nc2ccccc2[nH]1",
              "canonical_smiles": "COC(=O)Nc1nc2ccccc2[nH]1",
              "smiles_source": "vision_chemical_ocr_agent",
              "validation_status": "accepted",
              "mapping_confidence": 0.9,
              "agent_confidence": 0.88,
              "mapping_evidence": "direct label"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    result = upsert_chemical_agent_evidence(db_path, report_path)
    document = load_scraped_document(db_path, pdf_path=tmp_path / "paper.pdf", render_pages=False)

    assert result == {"inserted": 1, "skipped": 0}
    assert "Chemical agent SMILES: compound_id=6a" in document.pages[0].text
    assert "canonical_smiles=COC(=O)Nc1nc2ccccc2[nH]1" in document.pages[0].text
