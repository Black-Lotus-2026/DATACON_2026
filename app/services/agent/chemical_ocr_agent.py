from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Callable

from app.services.agent.llm import ChatCompletionsClient, LLMConfigurationError, LLMRequestError
from app.services.agent.specialized_skills import SpecializedSkill, load_specialized_skill


SmilesValidator = Callable[[str], tuple[str, str | None, str | None]]


class ChemicalOCRAgent:
    def __init__(
        self,
        data_analysis_path: Path,
        output_dir: Path,
        client: ChatCompletionsClient,
        *,
        skill: SpecializedSkill | None = None,
        limit: int | None = None,
        smiles_validator: SmilesValidator | None = None,
    ) -> None:
        self.data_analysis_path = data_analysis_path.resolve()
        self.output_dir = output_dir.resolve()
        self.client = client
        self.skill = skill or load_specialized_skill("chemical_ocr")
        self.limit = limit
        self.smiles_validator = smiles_validator or validate_smiles

    def run(self) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        raw_dir = self.output_dir / "chemical_ocr_raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        data_report = json.loads(self.data_analysis_path.read_text(encoding="utf-8"))
        work_items = _chemical_work_items(data_report)
        if self.limit is not None:
            work_items = work_items[: self.limit]

        records = []
        for index, item in enumerate(work_items, start=1):
            try:
                response = self.client.complete_with_images(
                    system=self.skill.prompt,
                    user=_build_chemical_ocr_prompt(item),
                    images=[(item["crop_label"], Path(item["image_path"]))],
                )
                analysis = _as_json_object(response["parsed_json"])
                raw_content = response["content"]
                request_error = response["parse_error"]
                usage = response["usage"]
            except (LLMConfigurationError, LLMRequestError) as exc:
                analysis = None
                raw_content = ""
                request_error = str(exc)
                usage = None

            raw_path = raw_dir / f"{index:04d}_{_safe_name(item['detection_id'])}.txt"
            raw_path.write_text(raw_content, encoding="utf-8")
            record = _finalize_record(
                item,
                analysis,
                request_error=request_error,
                usage=usage,
                raw_path=raw_path,
                validator=self.smiles_validator,
            )
            records.append(record)

        report = {
            "status": "completed",
            "stage": "chemical_ocr",
            "data_analysis_path": str(self.data_analysis_path),
            "skill": {
                "name": self.skill.name,
                "source_path": self.skill.source_path,
            },
            "work_items": len(work_items),
            "accepted": sum(item["validation_status"] == "accepted" for item in records),
            "needs_review": sum(item["validation_status"] == "needs_review" for item in records),
            "rejected": sum(item["validation_status"] == "rejected" for item in records),
            "records": records,
        }
        json_path = self.output_dir / "chemical_ocr_results.json"
        csv_path = self.output_dir / "chemical_ocr_results.csv"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_csv(csv_path, records)
        report["artifacts"] = {"json": str(json_path), "csv": str(csv_path)}
        return report


def _chemical_work_items(data_report: dict[str, Any]) -> list[dict[str, Any]]:
    work_items = []
    seen: set[tuple[str, str]] = set()
    for figure_result in data_report.get("results", []):
        analysis = figure_result.get("analysis")
        if not isinstance(analysis, dict):
            continue
        crops = {
            crop["crop_label"]: crop
            for crop in figure_result.get("crops", [])
            if isinstance(crop, dict) and crop.get("crop_label")
        }
        scaffolds = {
            item.get("crop_label"): item
            for item in analysis.get("scaffolds", [])
            if isinstance(item, dict) and item.get("crop_label")
        }
        for mapping in analysis.get("mappings", []):
            if not isinstance(mapping, dict):
                continue
            crop_label = str(mapping.get("crop_label", "")).strip()
            compound_id = str(mapping.get("compound_id", "")).strip()
            crop = crops.get(crop_label)
            if not crop or not compound_id:
                continue
            key = (compound_id, crop_label)
            if key in seen:
                continue
            seen.add(key)
            work_items.append(
                {
                    "figure_id": figure_result.get("figure_id"),
                    "page_number": figure_result.get("page_number"),
                    "caption": figure_result.get("caption") or "",
                    "compound_id": compound_id,
                    "crop_label": crop_label,
                    "detection_id": crop.get("detection_id"),
                    "image_path": crop.get("image_path"),
                    "bbox": crop.get("bbox"),
                    "molscribe_smiles": crop.get("molscribe_smiles"),
                    "molscribe_confidence": crop.get("molscribe_confidence"),
                    "mapping_confidence": mapping.get("confidence"),
                    "mapping_evidence": mapping.get("evidence"),
                    "scaffold": scaffolds.get(crop_label),
                    "image_analysis_summary": analysis.get("summary"),
                    "image_analysis_warnings": analysis.get("warnings", []),
                }
            )
    return work_items


def _build_chemical_ocr_prompt(item: dict[str, Any]) -> str:
    context = {
        "compound_id": item["compound_id"],
        "crop_label": item["crop_label"],
        "detection_id": item["detection_id"],
        "page_number": item["page_number"],
        "caption": item["caption"],
        "mapping_confidence": item["mapping_confidence"],
        "mapping_evidence": item["mapping_evidence"],
        "scaffold_warning": item["scaffold"],
        "image_analysis_summary": item["image_analysis_summary"],
        "image_analysis_warnings": item["image_analysis_warnings"],
        "untrusted_molscribe_smiles": item["molscribe_smiles"],
        "untrusted_molscribe_confidence": item["molscribe_confidence"],
    }
    return "\n\n".join(
        [
            "Analyze exactly one labeled chemical structure crop.",
            json.dumps(context, ensure_ascii=False, indent=2),
            "Return one JSON object according to the chemical OCR skill. Do not return markdown.",
        ]
    )


def _finalize_record(
    item: dict[str, Any],
    analysis: dict[str, Any] | None,
    *,
    request_error: str | None,
    usage: Any,
    raw_path: Path,
    validator: SmilesValidator,
) -> dict[str, Any]:
    llm_smiles = _clean_smiles(analysis.get("smiles") if analysis else None)
    molscribe_smiles = _clean_smiles(item.get("molscribe_smiles"))
    llm_validation = validator(llm_smiles) if llm_smiles else ("invalid", None, "not_returned")
    molscribe_validation = (
        validator(molscribe_smiles) if molscribe_smiles else ("invalid", None, "not_available")
    )

    if llm_validation[0] == "valid":
        final_smiles = llm_smiles
        canonical_smiles = llm_validation[1]
        source = "vision_chemical_ocr_agent"
        validation_status = "accepted"
        validation_error = None
    elif molscribe_validation[0] == "valid":
        final_smiles = molscribe_smiles
        canonical_smiles = molscribe_validation[1]
        source = "molscribe_fallback"
        validation_status = "accepted"
        validation_error = llm_validation[2]
    elif llm_validation[0] == "not_checked" and llm_smiles:
        final_smiles = llm_smiles
        canonical_smiles = None
        source = "vision_chemical_ocr_agent"
        validation_status = "needs_review"
        validation_error = llm_validation[2]
    else:
        final_smiles = "NOT_DETECTED"
        canonical_smiles = None
        source = "none"
        validation_status = "rejected"
        validation_error = llm_validation[2] or molscribe_validation[2]

    if item.get("scaffold") and item["scaffold"].get("requires_substituent_resolution"):
        final_smiles = "NOT_DETECTED"
        canonical_smiles = None
        source = "none"
        validation_status = "rejected"
        validation_error = "unresolved_scaffold_substituents"

    return {
        "compound_id": item["compound_id"],
        "figure_id": item["figure_id"],
        "page_number": item["page_number"],
        "crop_label": item["crop_label"],
        "detection_id": item["detection_id"],
        "smiles": final_smiles,
        "canonical_smiles": canonical_smiles,
        "smiles_source": source,
        "validation_status": validation_status,
        "validation_error": validation_error,
        "mapping_confidence": item["mapping_confidence"],
        "mapping_evidence": item["mapping_evidence"],
        "agent_confidence": analysis.get("confidence") if analysis else None,
        "agent_decision": analysis.get("decision") if analysis else None,
        "agent_candidate_agreement": analysis.get("candidate_agreement") if analysis else None,
        "agent_issues": analysis.get("issues", []) if analysis else [],
        "agent_evidence": analysis.get("evidence") if analysis else None,
        "molscribe_smiles": molscribe_smiles or None,
        "molscribe_confidence": item.get("molscribe_confidence"),
        "parse_or_request_error": request_error,
        "usage": usage,
        "raw_path": str(raw_path),
    }


def validate_smiles(smiles: str) -> tuple[str, str | None, str | None]:
    if not smiles:
        return "invalid", None, "empty_smiles"
    if "*" in smiles:
        return "invalid", None, "wildcard_or_unresolved_r_group"
    try:
        from rdkit import Chem
    except ImportError:
        return "not_checked", None, "rdkit_not_installed"

    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        return "invalid", None, "rdkit_parse_failed"
    return "valid", Chem.MolToSmiles(molecule, canonical=True), None


def _clean_smiles(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    if not cleaned or cleaned.upper() == "NOT_DETECTED":
        return ""
    return cleaned


def _as_json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    return None


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fieldnames = [
        "compound_id",
        "figure_id",
        "page_number",
        "detection_id",
        "smiles",
        "canonical_smiles",
        "smiles_source",
        "validation_status",
        "validation_error",
        "mapping_confidence",
        "agent_confidence",
        "molscribe_confidence",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def _safe_name(value: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value or "").strip("_") or "crop"
