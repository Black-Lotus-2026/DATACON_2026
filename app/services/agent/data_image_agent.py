from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from app.services.agent.llm import ChatCompletionsClient, LLMConfigurationError, LLMRequestError
from app.services.agent.specialized_skills import SpecializedSkill, load_specialized_skill


class DataImageAnalysisAgent:
    def __init__(
        self,
        sqlite_path: Path,
        output_dir: Path,
        client: ChatCompletionsClient,
        *,
        skill: SpecializedSkill | None = None,
        limit: int | None = None,
        max_crops_per_figure: int = 12,
    ) -> None:
        self.sqlite_path = sqlite_path.resolve()
        self.output_dir = output_dir.resolve()
        self.client = client
        self.skill = skill or load_specialized_skill("data_image_analysis")
        self.limit = limit
        self.max_crops_per_figure = max_crops_per_figure

    def run(self) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        raw_dir = self.output_dir / "data_image_raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        work_items = _load_figure_work_items(
            self.sqlite_path,
            limit=self.limit,
            max_crops_per_figure=self.max_crops_per_figure,
        )
        results = []
        for item in work_items:
            images = [("parent_figure", Path(item["image_path"]))]
            images.extend((crop["crop_label"], Path(crop["image_path"])) for crop in item["crops"])
            try:
                response = self.client.complete_with_images(
                    system=self.skill.prompt,
                    user=_build_data_image_prompt(item),
                    images=images,
                )
                analysis = _as_json_object(response["parsed_json"])
                status = "completed" if analysis is not None else "completed_with_parse_error"
                raw_content = response["content"]
                error = response["parse_error"]
                usage = response["usage"]
            except (LLMConfigurationError, LLMRequestError) as exc:
                analysis = None
                status = "failed"
                raw_content = ""
                error = str(exc)
                usage = None

            raw_path = raw_dir / f"{_safe_name(item['figure_id'])}.txt"
            raw_path.write_text(raw_content, encoding="utf-8")
            results.append(
                {
                    "status": status,
                    "figure_id": item["figure_id"],
                    "page_number": item["page_number"],
                    "image_path": item["image_path"],
                    "caption": item["caption"],
                    "crops": item["crops"],
                    "analysis": analysis,
                    "parse_or_request_error": error,
                    "usage": usage,
                    "raw_path": str(raw_path),
                }
            )

        report = {
            "status": "completed",
            "stage": "data_image_analysis",
            "sqlite_path": str(self.sqlite_path),
            "skill": {
                "name": self.skill.name,
                "source_path": self.skill.source_path,
            },
            "work_items": len(work_items),
            "completed": sum(item["status"] == "completed" for item in results),
            "failed": sum(item["status"] == "failed" for item in results),
            "results": results,
        }
        report_path = self.output_dir / "data_image_analysis.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["artifact"] = str(report_path)
        return report


def _load_figure_work_items(
    sqlite_path: Path,
    *,
    limit: int | None,
    max_crops_per_figure: int,
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    try:
        sql = """
            SELECT
              f.figure_id,
              f.page_number,
              f.label,
              f.caption,
              f.image_path,
              f.kind,
              p.text AS page_text
            FROM figures AS f
            LEFT JOIN pages AS p
              ON p.doc_id = f.doc_id
             AND p.file_id = f.file_id
             AND p.page_number = f.page_number
            WHERE EXISTS (
              SELECT 1
              FROM structure_detections AS d
              WHERE d.parent_figure_id = f.figure_id
            )
            ORDER BY f.page_number, f.figure_id
        """
        params: list[Any] = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        items = []
        for figure in conn.execute(sql, params):
            crops = [
                {
                    "crop_label": f"crop:{row['detection_id']}",
                    "detection_id": row["detection_id"],
                    "image_path": row["image_path"],
                    "bbox": _load_json(row["bbox_json"]),
                    "molscribe_smiles": row["smiles"],
                    "molscribe_confidence": row["confidence"],
                }
                for row in conn.execute(
                    """
                    SELECT detection_id, image_path, bbox_json, smiles, confidence
                    FROM structure_detections
                    WHERE parent_figure_id = ?
                    ORDER BY
                      CASE WHEN smiles IS NOT NULL AND trim(smiles) != '' THEN 0 ELSE 1 END,
                      detection_id
                    LIMIT ?
                    """,
                    (figure["figure_id"], max_crops_per_figure),
                )
            ]
            nearby = [
                {
                    "evidence_id": row["evidence_id"],
                    "page_number": row["page_number"],
                    "source_type": row["source_type"],
                    "text": " ".join((row["text"] or "").split())[:900],
                }
                for row in conn.execute(
                    """
                    SELECT evidence_id, page_number, source_type, text
                    FROM evidence_blocks
                    WHERE page_number BETWEEN ? AND ?
                      AND source_type IN ('paragraph', 'table_caption', 'table_row', 'figure_caption')
                    ORDER BY
                      CASE WHEN page_number = ? THEN 0 ELSE 1 END,
                      CASE source_type WHEN 'table_row' THEN 0 WHEN 'paragraph' THEN 1 ELSE 2 END,
                      evidence_id
                    LIMIT 12
                    """,
                    (max(1, figure["page_number"] - 1), figure["page_number"] + 1, figure["page_number"]),
                )
            ]
            items.append(
                {
                    "figure_id": figure["figure_id"],
                    "page_number": figure["page_number"],
                    "label": figure["label"],
                    "caption": figure["caption"] or "",
                    "image_path": figure["image_path"],
                    "kind": figure["kind"],
                    "page_text": " ".join((figure["page_text"] or "").split())[:2500],
                    "nearby_evidence": nearby,
                    "crops": crops,
                }
            )
        return items
    finally:
        conn.close()


def _build_data_image_prompt(item: dict[str, Any]) -> str:
    crop_manifest = [
        {
            "crop_label": crop["crop_label"],
            "detection_id": crop["detection_id"],
            "bbox": crop["bbox"],
            "untrusted_molscribe_smiles": crop["molscribe_smiles"],
            "untrusted_molscribe_confidence": crop["molscribe_confidence"],
        }
        for crop in item["crops"]
    ]
    return "\n\n".join(
        [
            f"Figure id: {item['figure_id']}",
            f"Page: {item['page_number']}",
            f"Kind: {item['kind']}",
            f"Caption: {item['caption'] or 'NOT_DETECTED'}",
            f"Page text: {item['page_text'] or 'NOT_DETECTED'}",
            "Crop manifest:\n" + json.dumps(crop_manifest, ensure_ascii=False, indent=2),
            "Nearby structured evidence:\n" + json.dumps(item["nearby_evidence"], ensure_ascii=False, indent=2),
            "Analyze the parent figure and labeled crops according to the skill. Return one JSON object only.",
        ]
    )


def _as_json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    return None


def _load_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "figure"
