import json
import sqlite3
from pathlib import Path

from app.services.scraper.storage import SCHEMA_SQL
from datacon_agent.evidence_agents import run_evidence_agents
from datacon_agent.scraper_context import load_scraped_document


def test_evidence_agents_publish_structured_context(tmp_path: Path) -> None:
    db_path = tmp_path / "scrape.sqlite"
    create_agent_fixture(db_path, tmp_path)

    summary = run_evidence_agents(db_path)
    document = load_scraped_document(db_path, pdf_path=tmp_path / "paper.pdf", render_pages=False)
    text = document.pages[0].text

    assert summary["table_measurement_agent"]["inserted"] == 1
    assert summary["compound_linking_agent"]["inserted"] == 1
    assert summary["compound_linking_agent"]["missing_smiles"] == 0
    assert summary["conflict_resolver_agent"]["inserted"] == 1
    assert summary["scaffold_resolver_agent"]["inserted"] == 1
    assert "Agent table measurement: compound_id=6a" in text
    assert "Agent compound link: compound_id=6a" in text
    assert "Agent conflict decision: compound_id=6a" in text
    assert "Agent scaffold resolution: status=needs_review" in text

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        assert conn.execute("SELECT COUNT(*) FROM agent_table_measurements").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM agent_compound_links").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM agent_conflict_decisions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM agent_scaffold_resolutions").fetchone()[0] == 1
        measurement = conn.execute(
            """
            SELECT compound_id, target_type, target_value, target_units, bacteria
            FROM agent_table_measurements
            """
        ).fetchone()
        assert dict(measurement) == {
            "compound_id": "6a",
            "target_type": "MIC",
            "target_value": "4",
            "target_units": "µg/mL",
            "bacteria": "Staphylococcus aureus",
        }
    finally:
        conn.close()


def test_table_measurement_agent_extracts_measurement_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "scrape.sqlite"
    create_antimicrobial_table_fixture(db_path, tmp_path)

    summary = run_evidence_agents(db_path)

    assert summary["table_measurement_agent"]["inserted"] == 4
    assert summary["table_measurement_agent"]["planned_tables"] == 1
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT compound_id, target_type, target_value, target_units, bacteria
                FROM agent_table_measurements
                ORDER BY bacteria
                """
            )
        ]
        metadata = json.loads(
            conn.execute(
                """
                SELECT metadata_json
                FROM agent_table_measurements
                WHERE bacteria = 'Staphylococcus aureus'
                """
            ).fetchone()["metadata_json"]
        )
    finally:
        conn.close()

    assert metadata["table_plan"]["compound_column_index"] == 0
    assert metadata["table_plan"]["target_type"] == "INHIBITION_ZONE"
    assert metadata["table_plan"]["target_units"] == "mm"
    assert metadata["column_plan"]["index"] == 1
    assert metadata["column_plan"]["column"] == "S. aureus"
    assert metadata["column_plan"]["target_type"] == "INHIBITION_ZONE"
    assert metadata["column_plan"]["target_units"] == "mm"
    assert metadata["column_plan"]["bacteria"] == "Staphylococcus aureus"
    assert metadata["column_plan"]["confidence"] > 0.8
    assert metadata["column_plan"]["reasons"] == [
        "numeric_cells",
        "bacteria:Staphylococcus aureus",
        "units:mm",
        "target_from_table",
    ]
    assert {tuple(row.items()) for row in rows} == {
        tuple(
            {
                "compound_id": "63a",
                "target_type": "INHIBITION_ZONE",
                "target_value": "21",
                "target_units": "mm",
                "bacteria": "Escherichia coli",
            }.items()
        ),
        tuple(
            {
                "compound_id": "63a",
                "target_type": "INHIBITION_ZONE",
                "target_value": "26",
                "target_units": "mm",
                "bacteria": "Pseudomonas aeruginosa",
            }.items()
        ),
        tuple(
            {
                "compound_id": "63a",
                "target_type": "INHIBITION_ZONE",
                "target_value": "28",
                "target_units": "mm",
                "bacteria": "Staphylococcus aureus",
            }.items()
        ),
        tuple(
            {
                "compound_id": "63a",
                "target_type": "INHIBITION_ZONE",
                "target_value": "19",
                "target_units": "mm",
                "bacteria": "Salmonella typhosa",
            }.items()
        ),
    }


def create_agent_fixture(db_path: Path, tmp_path: Path) -> None:
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
            (
                "doc:main:p0001",
                "doc",
                "main",
                1,
                100.0,
                100.0,
                "Compound 6a was tested against Staphylococcus aureus.",
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
                "Table 1. MIC values for compounds 6a-6c with R1 substituents.",
                "MIC scaffold table",
            ),
        )
        conn.execute(
            """
            INSERT INTO tables (
              table_id, doc_id, file_id, page_number, label, caption, columns_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "table1",
                "doc",
                "main",
                1,
                "Table 1",
                "MIC values against Staphylococcus aureus",
                '["compound", "MIC", "bacteria"]',
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
                "doc:main:p0001:table:row:0001",
                "doc",
                "main",
                1,
                "table_row",
                "6a | MIC 4 µg/mL | S. aureus",
                "MIC values against Staphylococcus aureus",
            ),
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
                '["6a", "MIC 4 µg/mL", "S. aureus"]',
                "6a | MIC 4 µg/mL | S. aureus",
            ),
        )
        conn.execute(
            """
            INSERT INTO evidence_blocks (
              evidence_id, doc_id, file_id, page_number, source_type, text, caption,
              metadata_json, parser, confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc:main:p0001:structure:0001:smiles",
                "doc",
                "main",
                1,
                "chemical_structure_smiles",
                "Chemical agent SMILES: compound_id=6a | smiles=COC(=O)Nc1nc2ccccc2[nH]1 | canonical_smiles=COC(=O)Nc1nc2ccccc2[nH]1",
                "6a",
                '{"compound_id": "6a"}',
                "chemical_ocr_agent",
                0.9,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def create_antimicrobial_table_fixture(db_path: Path, tmp_path: Path) -> None:
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
            ("doc:main:p0001", "doc", "main", 1, 100.0, 100.0, ""),
        )
        conn.execute(
            """
            INSERT INTO tables (
              table_id, doc_id, file_id, page_number, label, caption, columns_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "table4",
                "doc",
                "main",
                1,
                "Table 4",
                "Antimicrobial activity using the agar diffusion method. Inhibition Zone Diameters (mm)",
                '["Compound", "S. aureus", "P. aeruginosa", "E. coli", "S. typhosa"]',
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
                "doc:main:p0001:table:row:0001",
                "doc",
                "main",
                1,
                "table_row",
                "63a | 28 | 26 | 21 | 19",
                "Antimicrobial activity using the agar diffusion method. Inhibition Zone Diameters (mm)",
            ),
        )
        conn.execute(
            """
            INSERT INTO table_rows (row_id, table_id, evidence_id, row_index, cells_json, normalized_text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "row1",
                "table4",
                "doc:main:p0001:table:row:0001",
                1,
                '["63a", "28", "26", "21", "19"]',
                "63a | 28 | 26 | 21 | 19",
            ),
        )
        conn.commit()
    finally:
        conn.close()
