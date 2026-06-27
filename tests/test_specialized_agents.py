from __future__ import annotations

import base64
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services.agent.chemical_ocr_agent import ChemicalOCRAgent
from app.services.agent.data_image_agent import DataImageAnalysisAgent
from app.services.agent.specialized_skills import load_specialized_skill
from app.services.scraper.storage import SCHEMA_SQL


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class FakeVisionClient:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete_with_images(self, *, system: str, user: str, images: list[tuple[str, Path]]) -> dict:
        self.calls.append({"system": system, "user": user, "images": images})
        parsed = self.responses.pop(0)
        return {
            "content": json.dumps(parsed),
            "parsed_json": parsed,
            "parse_error": None,
            "usage": {"total_tokens": 1},
        }


class SpecializedAgentTests(unittest.TestCase):
    def test_specialized_skills_load(self) -> None:
        data_skill = load_specialized_skill("data_image_analysis")
        chemical_skill = load_specialized_skill("chemical_ocr")
        self.assertEqual(data_skill.name, "data-image-analysis")
        self.assertIn("Do not generate", data_skill.prompt)
        self.assertIn("NOT_DETECTED", chemical_skill.prompt)

    def test_two_agent_pipeline_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "scrape.sqlite"
            parent_image = root / "figure.png"
            crop_image = root / "crop.png"
            parent_image.write_bytes(PNG_1X1)
            crop_image.write_bytes(PNG_1X1)
            self._create_fixture_db(db_path, parent_image, crop_image)

            detection_id = "doc:main:p0001:scheme:scheme_1:structure_detection:decimer:0001"
            crop_label = f"crop:{detection_id}"
            data_client = FakeVisionClient(
                [
                    {
                        "image_id": "parent_figure",
                        "page_number": 1,
                        "summary": "One labeled product",
                        "compound_labels": [{"compound_id": "6a", "visible_text": "6a", "role": "product"}],
                        "mappings": [
                            {
                                "compound_id": "6a",
                                "crop_label": crop_label,
                                "confidence": 0.93,
                                "evidence": "direct adjacency",
                            }
                        ],
                        "scaffolds": [],
                        "unresolved": [],
                        "warnings": [],
                    }
                ]
            )
            output_dir = root / "agent_output"
            data_report = DataImageAnalysisAgent(db_path, output_dir, data_client).run()
            self.assertEqual(data_report["completed"], 1)
            self.assertEqual(len(data_client.calls[0]["images"]), 2)

            chemical_client = FakeVisionClient(
                [
                    {
                        "compound_id": "6a",
                        "crop_label": crop_label,
                        "smiles": "COC(=O)Nc1nc2ccccc2[nH]1",
                        "confidence": 0.9,
                        "decision": "accepted",
                        "candidate_agreement": "matches_molscribe",
                        "issues": [],
                        "evidence": "complete graph",
                    }
                ]
            )
            chemical_report = ChemicalOCRAgent(
                Path(data_report["artifact"]),
                output_dir,
                chemical_client,
                smiles_validator=lambda value: ("valid", value, None),
            ).run()
            self.assertEqual(chemical_report["accepted"], 1)
            record = chemical_report["records"][0]
            self.assertEqual(record["compound_id"], "6a")
            self.assertEqual(record["validation_status"], "accepted")
            self.assertEqual(record["smiles_source"], "vision_chemical_ocr_agent")
            self.assertTrue(Path(chemical_report["artifacts"]["csv"]).exists())

    @staticmethod
    def _create_fixture_db(db_path: Path, parent_image: Path, crop_image: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.execute(
                "INSERT INTO documents (doc_id, source_path, sha256) VALUES (?, ?, ?)",
                ("doc", "/tmp/source.pdf", "sha"),
            )
            conn.execute(
                "INSERT INTO files (file_id, doc_id, kind, path, sha256) VALUES (?, ?, ?, ?, ?)",
                ("main", "doc", "pdf", "/tmp/source.pdf", "sha"),
            )
            conn.execute(
                """
                INSERT INTO pages (page_id, doc_id, file_id, page_number, width, height, text)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("doc:main:p0001", "doc", "main", 1, 100.0, 100.0, "Compound 6a was synthesized."),
            )
            figure_id = "doc:main:p0001:scheme:scheme_1"
            conn.execute(
                """
                INSERT INTO figures (
                  figure_id, doc_id, file_id, page_number, label, caption,
                  image_path, bbox_json, kind, ocr_text, parser, confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    figure_id,
                    "doc",
                    "main",
                    1,
                    "Scheme 1",
                    "Synthesis of compound 6a.",
                    str(parent_image),
                    None,
                    "scheme",
                    "",
                    "fixture",
                    1.0,
                ),
            )
            task_id = f"{figure_id}:structure_detection"
            conn.execute(
                """
                INSERT INTO visual_tasks (
                  task_id, doc_id, file_id, page_number, task_type, target_type,
                  target_id, provider_hint, priority, reason, status, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    "doc",
                    "main",
                    1,
                    "chemical_structure_detection",
                    "figure",
                    figure_id,
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
                    f"{task_id}:decimer:0001",
                    task_id,
                    "doc",
                    "main",
                    1,
                    figure_id,
                    str(crop_image),
                    "[1, 1, 50, 50]",
                    None,
                    "COC(=O)Nc1nc2ccccc2[nH]1",
                    "decimer_segmentation",
                    0.88,
                    "{}",
                ),
            )
            conn.commit()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
