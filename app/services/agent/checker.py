from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.agent.llm import ChatCompletionsClient, LLMConfig, LLMConfigurationError, LLMRequestError, load_env_file
from app.services.agent.skills.loader import ChemXSkill, PromptVariant, select_chemx_skills
from app.services.scraper.pdf_scraper import scrape_pdf


FIELD_ALIASES = {
    "compound_id": ("compound", "molecule", "derivative", "ligand", "complex", "sample", "id"),
    "compound_name": ("compound", "name", "ligand", "complex", "material"),
    "name": ("name", "sample", "material", "nanoparticle"),
    "smiles": ("smiles", "structure", "chemical structure", "compound", "molecule"),
    "SMILES": ("smiles", "structure", "chemical structure", "ligand", "complex"),
    "SMILES_type": ("ligand", "environment", "complex"),
    "target_type": ("MIC", "pMIC", "IC50", "EC50", "activity", "measurement"),
    "target_relation": ("<", ">", "=", "less than", "greater than"),
    "target_value": ("MIC", "pMIC", "logK", "lgK", "IC50", "EC50", "activity", "value"),
    "target_units": ("ug/mL", "microg/mL", "mg/L", "mM", "uM", "units"),
    "bacteria": ("bacteria", "strain", "Staphylococcus", "aureus", "Escherichia", "coli", "E. coli", "S. aureus"),
    "strain": ("strain", "bacteria", "isolate"),
    "MDR": ("MDR", "multidrug", "resistant"),
    "mdr": ("MDR", "multidrug", "resistant"),
    "drug": ("drug", "antibiotic", "compound"),
    "FIC": ("FIC", "fractional inhibitory", "synergy"),
    "combined_MIC": ("combined MIC", "MIC", "combination"),
    "peptide_MIC": ("peptide MIC", "MIC", "peptide"),
    "effect": ("synergy", "additive", "antagonism", "effect"),
    "fold_increase_in_antibacterial_activity": ("fold", "increase", "antibacterial activity"),
    "viability_error": ("viability", "error", "standard deviation"),
    "activity": ("activity", "catalytic", "enzyme", "nanozyme"),
    "reaction_type": ("reaction", "substrate", "oxidase", "peroxidase", "catalase"),
    "km_value": ("Km", "Michaelis", "kinetic"),
    "km_unit": ("Km", "mM", "uM"),
    "vmax_value": ("Vmax", "kinetic", "velocity"),
    "vmax_unit": ("Vmax", "mM", "s-1", "min-1"),
    "ph": ("pH", "acidic", "basic"),
    "temperature": ("temperature", "C", "K"),
    "formula": ("formula", "composition", "material"),
    "surface": ("surface", "coating", "shell", "functional"),
    "shape": ("shape", "spherical", "rod", "cube"),
    "material": ("material", "nanoparticle", "composition"),
    "concentration": ("concentration", "dose", "mg/mL", "ug/mL", "mM"),
    "time_hr": ("time", "h", "hr", "hours"),
    "test": ("assay", "test", "method"),
    "test_indicator": ("indicator", "assay", "readout"),
    "cell_tissue": ("cell", "tissue", "line"),
    "cell_source": ("cell", "source", "line"),
    "cell_age": ("cell", "age"),
    "cell_morphology": ("morphology", "cell"),
    "human_animal": ("human", "animal", "mouse", "rat"),
    "no_of_cells_cells_well": ("cells/well", "cells per well", "seeding"),
    "core_nm": ("core", "nm", "diameter", "size"),
    "hydrodynamic_nm": ("hydrodynamic", "DLS", "nm", "diameter"),
    "size_in_medium_nm": ("medium", "size", "nm"),
    "potential_mv": ("potential", "mV", "zeta"),
    "zeta_in_medium_mv": ("zeta", "mV", "medium"),
    "surface_charge": ("surface charge", "zeta", "charge"),
    "coat_functional_group": ("coating", "functional group", "surface"),
    "synthesis_method": ("synthesis", "prepared", "method"),
    "np": ("nanoparticle", "NP", "AgNP"),
    "NP": ("nanoparticle", "NP"),
    "NP_synthesis": ("synthesis", "prepared", "NP"),
    "np_synthesis": ("synthesis", "prepared", "NP"),
    "NP_size_avg_nm": ("average size", "diameter", "nm", "TEM", "DLS"),
    "NP_size_min_nm": ("minimum size", "size range", "nm"),
    "NP_size_max_nm": ("maximum size", "size range", "nm"),
    "np_size_avg_nm": ("average size", "diameter", "nm", "TEM", "DLS"),
    "np_size_min_nm": ("minimum size", "size range", "nm"),
    "np_size_max_nm": ("maximum size", "size range", "nm"),
    "zeta_potential_mV": ("zeta", "potential", "mV"),
    "zoi_np_mm": ("zone of inhibition", "ZOI", "mm"),
    "coating": ("coating", "capped", "surface"),
    "method": ("method", "assay", "diffusion", "broth"),
    "precursor_of_np": ("precursor", "silver nitrate", "AgNO3"),
    "concentration_of_precursor_mM": ("precursor", "concentration", "mM"),
    "ph_during_synthesis": ("pH", "synthesis"),
    "temperature_for_extract_C": ("temperature", "extract", "C"),
    "duration_preparing_extract_min": ("duration", "extract", "min"),
    "solvent_for_extract": ("solvent", "extract"),
    "time_set_hours": ("time", "hours", "incubation"),
    "name_cocrystal": ("cocrystal", "co-crystal", "name"),
    "name_drug": ("drug", "API", "active pharmaceutical"),
    "name_coformer": ("coformer", "co-former"),
    "SMILES_drug": ("SMILES", "drug", "structure"),
    "SMILES_coformer": ("SMILES", "coformer", "structure"),
    "ratio_cocrystal": ("ratio", "stoichiometry", "cocrystal"),
    "photostability_change": ("photostability", "stability", "light"),
    "np_core": ("core", "magnetic", "nanoparticle"),
    "np_shell": ("shell", "coating", "surface"),
    "np_shell_2": ("shell", "coating", "surface"),
    "core_shell_formula": ("formula", "core", "shell"),
    "squid_sat_mag": ("saturation magnetization", "Ms", "emu/g"),
    "squid_rem_mag": ("remanent magnetization", "Mr", "emu/g"),
    "squid_temperature": ("SQUID", "temperature", "K"),
    "squid_h_max": ("SQUID", "field", "Oe", "T"),
    "coercivity": ("coercivity", "Hc", "Oe"),
    "hc_kOe": ("coercivity", "Hc", "kOe"),
    "exchange_bias_shift_Oe": ("exchange bias", "shift", "Oe"),
    "vertical_loop_shift_M_vsl_emu_g": ("vertical loop shift", "emu/g"),
    "fc_field_T": ("field cooled", "FC", "T"),
    "mri_r1": ("MRI", "r1", "relaxivity"),
    "mri_r2": ("MRI", "r2", "relaxivity"),
    "htherm_sar": ("SAR", "hyperthermia", "specific absorption"),
    "instrument": ("instrument", "SQUID", "VSM", "MRI"),
    "xrd_scherrer_size": ("XRD", "Scherrer", "size"),
    "space_group_core": ("space group", "core", "XRD"),
    "space_group_shell": ("space group", "shell", "XRD"),
    "np_hydro_size": ("hydrodynamic", "DLS", "size"),
    "emic_size": ("electron microscopy", "TEM", "SEM", "size"),
    "zfc_h_meas": ("ZFC", "field", "measurement"),
}

NUMERIC_RE = re.compile(r"(?<![A-Za-z])(?:[<>]=?|=)?\s*\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?")
CHEMISH_RE = re.compile(r"\b(?:SMILES|MIC|pMIC|IC50|EC50|AgNP|Fe3O4|TiO2|SiO2|ZnO|AuNP|DOTA|logK|lgK|Km|Vmax)\b", re.I)


@dataclass(frozen=True)
class EvidenceRow:
    evidence_id: str
    page_number: int | None
    source_type: str
    section: str | None
    caption: str | None
    text: str
    parser: str | None
    confidence: float | None


@dataclass(frozen=True)
class ScraperBundle:
    sqlite_path: Path
    doc_id: str | None
    source_path: str | None
    diagnostics: dict[str, Any]
    counts_by_source_type: dict[str, int]
    evidence: tuple[EvidenceRow, ...]
    tables_count: int
    figures_count: int
    visual_tasks_count: int
    structure_detections_count: int
    smiles_count: int


class CheckerAgent:
    def __init__(
        self,
        sqlite_path: Path,
        output_dir: Path,
        *,
        domain: str | None = None,
        top_k: int = 16,
        max_evidence: int = 5000,
        run_llm: bool = False,
        llm_config: LLMConfig | None = None,
        llm_top_k: int = 12,
    ) -> None:
        self.sqlite_path = sqlite_path
        self.output_dir = output_dir
        self.domain = domain
        self.top_k = top_k
        self.max_evidence = max_evidence
        self.run_llm = run_llm
        self.llm_config = llm_config
        self.llm_top_k = llm_top_k

    def run(self) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        bundle = load_scraper_bundle(self.sqlite_path, max_evidence=self.max_evidence)
        skills, skill_warning = select_chemx_skills(self.domain)
        checks = [self._check_skill(skill, bundle) for skill in skills]
        checks.sort(key=lambda item: item["score"], reverse=True)
        skills_by_name = {skill.name: skill for skill in skills}

        report = {
            "status": "completed",
            "mode": "single_agent_checker_with_llm" if self.run_llm else "single_agent_checker",
            "domain": self.domain,
            "skill_warning": skill_warning,
            "source": {
                "sqlite_path": str(bundle.sqlite_path),
                "doc_id": bundle.doc_id,
                "source_path": bundle.source_path,
            },
            "scraper_summary": {
                "diagnostics": bundle.diagnostics,
                "counts_by_source_type": bundle.counts_by_source_type,
                "tables_count": bundle.tables_count,
                "figures_count": bundle.figures_count,
                "visual_tasks_count": bundle.visual_tasks_count,
                "structure_detections_count": bundle.structure_detections_count,
                "smiles_count": bundle.smiles_count,
                "evidence_loaded": len(bundle.evidence),
            },
            "pipeline_checks": self._pipeline_checks(bundle),
            "skill_checks": checks,
        }
        if self.run_llm:
            report["llm_extraction"] = self._run_llm_extraction(checks, skills_by_name)

        report_path = self.output_dir / "agent_report.json"
        markdown_path = self.output_dir / "agent_report.md"
        candidates_path = self.output_dir / "candidate_evidence.jsonl"
        report["artifacts"] = {
            "json": str(report_path),
            "markdown": str(markdown_path),
            "candidate_evidence_jsonl": str(candidates_path),
        }
        if self.run_llm:
            report["artifacts"]["llm_result_json"] = str(self.output_dir / "llm_result.json")
            report["artifacts"]["llm_raw_txt"] = str(self.output_dir / "llm_raw.txt")
            report["artifacts"]["final_table_csv"] = str(self.output_dir / "final_table.csv")
            report["artifacts"]["final_table_markdown"] = str(self.output_dir / "final_table.md")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
        candidates_path.write_text(render_candidates_jsonl(checks), encoding="utf-8")
        return report

    def _run_llm_extraction(
        self,
        checks: list[dict[str, Any]],
        skills_by_name: dict[str, ChemXSkill],
    ) -> dict[str, Any]:
        if not checks:
            result = {"status": "skipped", "reason": "No skill checks were produced."}
            self._write_llm_artifacts(result, raw_text="")
            return result

        check = checks[0]
        skill = skills_by_name[check["skill"]]
        variant = _select_variant(skill, check)
        candidates = select_llm_candidates(check["candidate_evidence"], limit=self.llm_top_k)
        if not candidates:
            result = {
                "status": "skipped",
                "reason": f"No candidate evidence was found for skill {skill.name}.",
                "skill": skill.name,
            }
            self._write_llm_artifacts(result, raw_text="")
            return result

        try:
            config = self.llm_config or LLMConfig.from_env()
            client = ChatCompletionsClient(config)
            response = client.complete(
                system=build_llm_system_prompt(skill),
                user=build_llm_user_prompt(skill, variant, candidates),
            )
        except (LLMConfigurationError, LLMRequestError) as exc:
            result = {
                "status": "failed",
                "error": str(exc),
                "skill": skill.name,
                "variant": variant.name,
                "candidate_count": len(candidates),
            }
            self._write_llm_artifacts(result, raw_text="")
            return result

        result = {
            "status": "completed" if response["parse_error"] is None else "completed_with_parse_error",
            "provider": config.public_dict(),
            "skill": skill.name,
            "display_name": skill.display_name,
            "variant": variant.name,
            "candidate_count": len(candidates),
            "parsed_json": response["parsed_json"],
            "parse_error": response["parse_error"],
            "raw_content": response["content"],
            "usage": response["usage"],
        }
        self._write_llm_artifacts(result, raw_text=response["content"])
        return result

    def _write_llm_artifacts(self, result: dict[str, Any], *, raw_text: str) -> None:
        (self.output_dir / "llm_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.output_dir / "llm_raw.txt").write_text(raw_text, encoding="utf-8")
        _write_final_tables(self.output_dir, result.get("parsed_json"))

    def _check_skill(self, skill: ChemXSkill, bundle: ScraperBundle) -> dict[str, Any]:
        field_checks = [self._check_field(field, bundle.evidence) for field in skill.expected_fields]
        coverage = _coverage_ratio(field_checks)
        candidates = rank_candidate_evidence(bundle.evidence, skill, top_k=self.top_k)
        variant_scores = [score_variant(variant, bundle.evidence) for variant in skill.variants]
        variant_scores.sort(key=lambda item: item["score"], reverse=True)
        score = round((coverage * 0.62) + (_candidate_score(candidates) * 0.26) + (_structure_score(skill, bundle) * 0.12), 3)
        status = _skill_status(score, coverage, candidates, skill, bundle)

        return {
            "skill": skill.name,
            "display_name": skill.display_name,
            "status": status,
            "score": score,
            "coverage_ratio": coverage,
            "instructions": skill.instructions,
            "prompt_variants": [variant.name for variant in skill.variants],
            "variant_scores": variant_scores,
            "expected_fields": list(skill.expected_fields),
            "field_checks": field_checks,
            "candidate_evidence": candidates,
            "recommendations": _recommendations(skill, bundle, coverage, candidates),
            "skill_source": {
                "local_path": skill.source_path,
                "upstream_url": skill.upstream_url,
            },
        }

    def _check_field(self, field: str, evidence: tuple[EvidenceRow, ...]) -> dict[str, Any]:
        terms = terms_for_field(field)
        examples = []
        hits = 0
        for row in evidence:
            matched = matched_terms(row.text, terms)
            if not matched:
                continue
            hits += 1
            if len(examples) < 3:
                examples.append(
                    {
                        "evidence_id": row.evidence_id,
                        "page_number": row.page_number,
                        "source_type": row.source_type,
                        "matched_terms": matched[:8],
                        "snippet": snippet(row.text),
                    }
                )
        if hits >= 3:
            status = "present"
        elif hits:
            status = "partial"
        else:
            status = "missing"
        return {"field": field, "status": status, "hits": hits, "examples": examples}

    def _pipeline_checks(self, bundle: ScraperBundle) -> list[dict[str, Any]]:
        checks = [
            {
                "name": "scraper_sqlite",
                "status": "pass" if bundle.sqlite_path.exists() else "fail",
                "detail": str(bundle.sqlite_path),
            },
            {
                "name": "evidence_blocks",
                "status": "pass" if bundle.evidence else "fail",
                "detail": f"{len(bundle.evidence)} evidence blocks loaded",
            },
            {
                "name": "table_rows",
                "status": "pass" if bundle.counts_by_source_type.get("table_row", 0) else "warn",
                "detail": f"{bundle.counts_by_source_type.get('table_row', 0)} table-row evidence blocks",
            },
            {
                "name": "captions",
                "status": "pass"
                if bundle.counts_by_source_type.get("table_caption", 0) or bundle.counts_by_source_type.get("figure_caption", 0)
                else "warn",
                "detail": "caption evidence helps bind extracted values to tables and figures",
            },
            {
                "name": "structure_smiles",
                "status": "pass" if bundle.smiles_count else "warn",
                "detail": f"{bundle.smiles_count} OCSR SMILES evidence blocks",
            },
        ]
        if bundle.visual_tasks_count and not bundle.smiles_count:
            checks.append(
                {
                    "name": "visual_followup",
                    "status": "warn",
                    "detail": f"{bundle.visual_tasks_count} visual tasks exist; run visual/OCSR executors before final extraction if structures are required",
                }
            )
        return checks


def run_agent_check(
    source: Path,
    *,
    output_dir: Path | None = None,
    domain: str | None = None,
    doc_id: str | None = None,
    top_k: int = 16,
    max_evidence: int = 5000,
    run_llm: bool = False,
    llm_config: LLMConfig | None = None,
    llm_top_k: int = 12,
) -> dict[str, Any]:
    source = source.resolve()
    sqlite_path: Path
    report_dir: Path

    if source.is_dir():
        sqlite_path = source / "scrape.sqlite"
        if not sqlite_path.exists():
            raise FileNotFoundError(f"No scrape.sqlite found in {source}")
        report_dir = (output_dir or source / "agent_check").resolve()
    elif source.suffix.lower() == ".pdf":
        base_dir = (output_dir or Path("runs") / f"agent-{slug(source.stem)}").resolve()
        scrape_dir = base_dir / "scrape"
        scrape_result = scrape_pdf(source, scrape_dir, doc_id=doc_id)
        sqlite_path = Path(scrape_result.sqlite_path).resolve()
        report_dir = base_dir / "agent_check"
    elif source.suffix.lower() in {".sqlite", ".db"}:
        sqlite_path = source
        report_dir = (output_dir or source.parent / "agent_check").resolve()
    else:
        raise ValueError(f"Expected a PDF, scrape.sqlite, or run directory, got {source}")

    agent = CheckerAgent(
        sqlite_path,
        report_dir,
        domain=domain,
        top_k=top_k,
        max_evidence=max_evidence,
        run_llm=run_llm,
        llm_config=llm_config,
        llm_top_k=llm_top_k,
    )
    return agent.run()


def load_scraper_bundle(sqlite_path: Path, *, max_evidence: int) -> ScraperBundle:
    sqlite_path = sqlite_path.resolve()
    if not sqlite_path.exists():
        raise FileNotFoundError(sqlite_path)

    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    try:
        doc_row = _first_row(conn, "SELECT doc_id, source_path FROM documents ORDER BY created_at DESC LIMIT 1")
        diagnostics = _load_diagnostics(conn, doc_row["doc_id"] if doc_row else None)
        counts_by_source_type = {
            row["source_type"]: row["count"]
            for row in conn.execute(
                "SELECT source_type, COUNT(*) AS count FROM evidence_blocks GROUP BY source_type ORDER BY source_type"
            )
        }
        evidence = tuple(
            EvidenceRow(
                evidence_id=row["evidence_id"],
                page_number=row["page_number"],
                source_type=row["source_type"],
                section=row["section"],
                caption=row["caption"],
                text=row["text"] or "",
                parser=row["parser"],
                confidence=row["confidence"],
            )
            for row in conn.execute(
                """
                SELECT evidence_id, page_number, source_type, section, caption, text, parser, confidence
                FROM evidence_blocks
                ORDER BY page_number, evidence_id
                LIMIT ?
                """,
                (max_evidence,),
            )
        )
        return ScraperBundle(
            sqlite_path=sqlite_path,
            doc_id=doc_row["doc_id"] if doc_row else None,
            source_path=doc_row["source_path"] if doc_row else None,
            diagnostics=diagnostics,
            counts_by_source_type=counts_by_source_type,
            evidence=evidence,
            tables_count=_count(conn, "tables"),
            figures_count=_count(conn, "figures"),
            visual_tasks_count=_count(conn, "visual_tasks"),
            structure_detections_count=_count(conn, "structure_detections"),
            smiles_count=_count_smiles(conn),
        )
    finally:
        conn.close()


def rank_candidate_evidence(evidence: tuple[EvidenceRow, ...], skill: ChemXSkill, *, top_k: int) -> list[dict[str, Any]]:
    ranked = []
    terms = tuple(_ordered_unique([*skill.keywords, *terms_for_fields(skill.expected_fields)]))
    for row in evidence:
        score = evidence_score(row, terms)
        if score <= 0:
            continue
        ranked.append((score, row, matched_terms(row.text, terms)))

    ranked.sort(key=lambda item: item[0], reverse=True)
    candidates = []
    for rank, (score, row, matches) in enumerate(ranked[:top_k], start=1):
        candidates.append(
            {
                "rank": rank,
                "score": round(score, 3),
                "evidence_id": row.evidence_id,
                "page_number": row.page_number,
                "source_type": row.source_type,
                "matched_terms": matches[:12],
                "snippet": snippet(row.text, limit=520),
            }
        )
    return candidates


def select_llm_candidates(candidates: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    """Keep LLM context balanced across narrative, tables, and OCSR output."""
    if limit <= 0:
        return []

    quota = max(1, limit // 3)
    context_quota = max(1, limit - (quota * 2))
    table_rows = [item for item in candidates if item["source_type"] == "table_row"]
    measurement_rows = [
        item
        for item in table_rows
        if any(
            term.lower() in {"mic", "pmic", "mic50", "mic80", "ic50", "ec50", "fic", "km", "vmax"}
            for term in item["matched_terms"]
        )
    ]
    if measurement_rows:
        table_rows = measurement_rows
    structures = [item for item in candidates if item["source_type"] == "chemical_structure_smiles"]
    context = [
        item
        for item in candidates
        if item["source_type"] not in {"table_row", "chemical_structure_image", "chemical_structure_smiles"}
    ]

    selected = [*context[:context_quota], *table_rows[:quota]]
    anchor_pages = [item["page_number"] for item in selected if item["page_number"] is not None]
    if anchor_pages:
        structures.sort(
            key=lambda item: (
                min(abs(item["page_number"] - page) for page in anchor_pages)
                if item["page_number"] is not None
                else math.inf,
                item["rank"],
            )
        )
    selected.extend(structures[:quota])

    selected_ids = {item["evidence_id"] for item in selected}
    for item in candidates:
        if len(selected) >= limit:
            break
        if item["evidence_id"] in selected_ids or item["source_type"] == "chemical_structure_image":
            continue
        selected.append(item)
        selected_ids.add(item["evidence_id"])
    selected.sort(key=lambda item: item["rank"])
    return selected[:limit]


def score_variant(variant: PromptVariant, evidence: tuple[EvidenceRow, ...]) -> dict[str, Any]:
    terms = variant.keywords[:48]
    scores = [evidence_score(row, terms) for row in evidence]
    total = sum(score for score in scores if score > 0)
    hits = sum(1 for score in scores if score > 0)
    return {
        "variant": variant.name,
        "constant_name": variant.constant_name,
        "score": round(math.log1p(total), 3),
        "hits": hits,
        "expected_fields": list(variant.expected_fields),
    }


def evidence_score(row: EvidenceRow, terms: tuple[str, ...]) -> float:
    text = row.text
    matches = matched_terms(text, terms)
    if not matches:
        return 0.0
    score = float(len(matches))
    if row.source_type == "table_row":
        score += 1.25
    elif row.source_type in {"table_caption", "figure_caption"}:
        score += 0.75
    elif row.source_type in {"chemical_structure_smiles", "chemical_structure_image"}:
        score += 1.0
    if NUMERIC_RE.search(text):
        score += 0.5
    if CHEMISH_RE.search(text):
        score += 0.7
    if row.confidence:
        score += min(0.5, max(0.0, row.confidence - 0.5))
    return score


def terms_for_field(field: str) -> tuple[str, ...]:
    base = [field, field.replace("_", " ")]
    base.extend(part for part in re.split(r"[_\W]+", field) if len(part) > 1)
    base.extend(FIELD_ALIASES.get(field, ()))
    base.extend(FIELD_ALIASES.get(field.lower(), ()))
    return tuple(_ordered_unique(base))


def terms_for_fields(fields: tuple[str, ...]) -> list[str]:
    terms: list[str] = []
    for field in fields:
        terms.extend(terms_for_field(field))
    return terms


def matched_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    matches = []
    for term in terms:
        clean = term.strip()
        if not clean:
            continue
        lowered_term = clean.lower()
        if lowered_term.isalnum():
            found = re.search(rf"(?<!\w){re.escape(lowered_term)}(?!\w)", lowered) is not None
        else:
            found = lowered_term in lowered
        if found:
            matches.append(clean)
    return _ordered_unique(matches)


def render_markdown_report(report: dict[str, Any]) -> str:
    source = report["source"]
    summary = report["scraper_summary"]
    lines = [
        "# Single-agent scraper check",
        "",
        f"- SQLite: `{source['sqlite_path']}`",
        f"- Document: `{source.get('doc_id') or 'unknown'}`",
        f"- Source PDF: `{source.get('source_path') or 'unknown'}`",
        f"- Evidence loaded: {summary['evidence_loaded']}",
        f"- Tables: {summary['tables_count']}",
        f"- Figures: {summary['figures_count']}",
        f"- Visual tasks: {summary['visual_tasks_count']}",
        f"- OCSR SMILES: {summary['smiles_count']}",
    ]
    if report.get("skill_warning"):
        lines.extend(["", f"> {report['skill_warning']}"])

    lines.extend(["", "## Pipeline checks"])
    for check in report["pipeline_checks"]:
        lines.append(f"- {check['status'].upper()} `{check['name']}`: {check['detail']}")

    lines.extend(["", "## Skill checks"])
    for item in report["skill_checks"]:
        lines.extend(
            [
                f"### {item['display_name']} (`{item['skill']}`)",
                f"- Status: `{item['status']}`",
                f"- Score: {item['score']}",
                f"- Field coverage: {item['coverage_ratio']}",
                f"- Variants: {', '.join(item['prompt_variants'])}",
                f"- Expected fields: {', '.join(item['expected_fields'])}",
            ]
        )
        if item["candidate_evidence"]:
            best = item["candidate_evidence"][0]
            lines.append(f"- Top evidence: page {best['page_number']}, `{best['source_type']}`, score {best['score']}")
            lines.append(f"  - {best['snippet']}")
        for recommendation in item["recommendations"]:
            lines.append(f"- Recommendation: {recommendation}")
    if report.get("llm_extraction"):
        llm = report["llm_extraction"]
        lines.extend(["", "## LLM extraction"])
        lines.append(f"- Status: `{llm['status']}`")
        if llm.get("provider"):
            lines.append(f"- Provider: `{llm['provider']['provider']}` / `{llm['provider']['model']}`")
        if llm.get("skill"):
            lines.append(f"- Skill: `{llm['skill']}`")
        if llm.get("variant"):
            lines.append(f"- Variant: `{llm['variant']}`")
        if llm.get("parsed_json") is not None:
            parsed = llm["parsed_json"]
            size = len(parsed) if isinstance(parsed, list) else 1
            lines.append(f"- Parsed records: {size}")
        if llm.get("parse_error"):
            lines.append(f"- Parse error: {llm['parse_error']}")
        if llm.get("error"):
            lines.append(f"- Error: {llm['error']}")
    lines.append("")
    return "\n".join(lines)


def render_candidates_jsonl(checks: list[dict[str, Any]]) -> str:
    lines = []
    for check in checks:
        for candidate in check["candidate_evidence"]:
            row = {
                "skill": check["skill"],
                "display_name": check["display_name"],
                **candidate,
            }
            lines.append(json.dumps(row, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def snippet(text: str, *, limit: int = 360) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "document"


def build_llm_system_prompt(skill: ChemXSkill) -> str:
    return "\n".join(
        [
            skill.instructions,
            "You are a single ChemX extraction agent working only from provided scraper evidence.",
            "Extract only facts supported by the evidence snippets.",
            "Preserve the JSON field names requested by the ChemX prompt skill.",
            "If a required field is absent in the evidence, use NOT_DETECTED.",
            "Return a JSON array only. Do not include markdown, prose, or citations outside JSON fields.",
        ]
    )


def build_llm_user_prompt(skill: ChemXSkill, variant: PromptVariant, candidates: list[dict[str, Any]]) -> str:
    evidence_lines = []
    for candidate in candidates:
        evidence_lines.append(
            "\n".join(
                [
                    f"[{candidate['rank']}] evidence_id={candidate['evidence_id']}",
                    f"page={candidate['page_number']} source_type={candidate['source_type']} score={candidate['score']}",
                    f"matched_terms={', '.join(candidate['matched_terms'])}",
                    f"text={candidate['snippet']}",
                ]
            )
        )

    return "\n\n".join(
        [
            f"ChemX skill: {skill.display_name} ({skill.name})",
            f"Prompt variant: {variant.name}",
            "Original ChemX extraction prompt:",
            variant.prompt,
            "Structured scraper evidence snippets:",
            "\n\n".join(evidence_lines),
            "Return the final extraction JSON array now.",
        ]
    )


def _select_variant(skill: ChemXSkill, check: dict[str, Any]) -> PromptVariant:
    if not skill.variants:
        raise ValueError(f"Skill {skill.name} has no prompt variants")
    variant_scores = check.get("variant_scores") or []
    if not variant_scores:
        return skill.variants[0]
    best = variant_scores[0]["variant"]
    for variant in skill.variants:
        if variant.name == best:
            return variant
    return skill.variants[0]


def _load_diagnostics(conn: sqlite3.Connection, doc_id: str | None) -> dict[str, Any]:
    if not doc_id:
        return {}
    row = _first_row(conn, "SELECT * FROM diagnostics WHERE doc_id = ?", (doc_id,))
    if not row:
        return {}
    result = dict(row)
    notes_json = result.pop("notes_json", "[]")
    try:
        result["notes"] = json.loads(notes_json)
    except json.JSONDecodeError:
        result["notes"] = []
    return result


def _count(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _count_smiles(conn: sqlite3.Connection) -> int:
    evidence_count = 0
    if _table_exists(conn, "evidence_blocks"):
        evidence_count = int(
            conn.execute("SELECT COUNT(*) FROM evidence_blocks WHERE source_type = 'chemical_structure_smiles'").fetchone()[0]
        )
    detection_count = 0
    if _table_exists(conn, "structure_detections"):
        detection_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM structure_detections WHERE smiles IS NOT NULL AND trim(smiles) != ''"
            ).fetchone()[0]
        )
    # A successful OCSR result is stored in both tables under the same
    # detection id, so adding the counts would report every SMILES twice.
    return evidence_count or detection_count


def _write_final_tables(output_dir: Path, parsed_json: Any) -> None:
    csv_path = output_dir / "final_table.csv"
    markdown_path = output_dir / "final_table.md"
    rows = parsed_json if isinstance(parsed_json, list) else [parsed_json]
    rows = [row for row in rows if isinstance(row, dict)]
    if not rows:
        csv_path.unlink(missing_ok=True)
        markdown_path.unlink(missing_ok=True)
        return

    fieldnames = _ordered_unique([key for row in rows for key in row])
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _table_value(row.get(key)) for key in fieldnames})

    header = "| " + " | ".join(_markdown_cell(field) for field in fieldnames) + " |"
    separator = "| " + " | ".join("---" for _ in fieldnames) + " |"
    body = [
        "| " + " | ".join(_markdown_cell(_table_value(row.get(field))) for field in fieldnames) + " |"
        for row in rows
    ]
    markdown_path.write_text("\n".join([header, separator, *body]) + "\n", encoding="utf-8")


def _table_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return value


def _markdown_cell(value: Any) -> str:
    return str(value).replace("|", r"\|").replace("\n", " ")


def _first_row(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table,)).fetchone()
    return row is not None


def _coverage_ratio(field_checks: list[dict[str, Any]]) -> float:
    if not field_checks:
        return 0.0
    value = 0.0
    for check in field_checks:
        if check["status"] == "present":
            value += 1.0
        elif check["status"] == "partial":
            value += 0.5
    return round(value / len(field_checks), 3)


def _candidate_score(candidates: list[dict[str, Any]]) -> float:
    if not candidates:
        return 0.0
    best = candidates[0]["score"]
    return round(min(1.0, math.log1p(best) / 3.0), 3)


def _structure_score(skill: ChemXSkill, bundle: ScraperBundle) -> float:
    needs_structure = any(field.lower() == "smiles" or "smiles" in field.lower() for field in skill.expected_fields)
    if not needs_structure:
        return 1.0
    if bundle.smiles_count:
        return 1.0
    if bundle.structure_detections_count:
        return 0.55
    if bundle.visual_tasks_count:
        return 0.35
    return 0.15


def _skill_status(
    score: float,
    coverage: float,
    candidates: list[dict[str, Any]],
    skill: ChemXSkill,
    bundle: ScraperBundle,
) -> str:
    needs_structure = any("smiles" in field.lower() for field in skill.expected_fields)
    if not candidates:
        return "low_signal"
    if needs_structure and not bundle.smiles_count:
        return "needs_visual_or_ocsr"
    if score >= 0.68 and coverage >= 0.55:
        return "ready_for_single_agent_review"
    if score >= 0.42:
        return "partial_evidence"
    return "low_signal"


def _recommendations(
    skill: ChemXSkill,
    bundle: ScraperBundle,
    coverage: float,
    candidates: list[dict[str, Any]],
) -> list[str]:
    recommendations = []
    needs_structure = any("smiles" in field.lower() for field in skill.expected_fields)
    if needs_structure and not bundle.smiles_count:
        recommendations.append("Run visual_executor and ocsr_executor before final JSON extraction because this skill expects SMILES.")
    if not bundle.counts_by_source_type.get("table_row"):
        recommendations.append("Table evidence is absent; verify pdfplumber/PyMuPDF table extraction or add table OCR.")
    if coverage < 0.5:
        recommendations.append("Use this report as routing only; field evidence coverage is still below extraction-ready level.")
    if candidates:
        recommendations.append("Feed top candidate_evidence snippets plus the skill prompt into the first LLM extraction pass.")
    return recommendations


def _ordered_unique(values: list[str] | tuple[str, ...]) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        cleaned = str(value).strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run PDF -> scraper SQLite -> single-agent ChemX evidence checker.",
    )
    parser.add_argument("source", type=Path, help="PDF file, scrape.sqlite, or a run directory containing scrape.sqlite")
    parser.add_argument("--out", type=Path, default=None, help="Output directory for scraper/checker artifacts")
    parser.add_argument("--domain", default=None, help="ChemX domain name. If omitted, all local prompt skills are checked.")
    parser.add_argument("--doc-id", default=None, help="Optional document id when source is a PDF")
    parser.add_argument("--top-k", type=int, default=16, help="Candidate evidence rows per skill")
    parser.add_argument("--max-evidence", type=int, default=5000, help="Maximum evidence blocks to load from SQLite")
    parser.add_argument("--run-llm", action="store_true", help="Call the configured LLM provider for the top-ranked skill")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Local env file with VSEGPT_API_KEY")
    parser.add_argument("--llm-provider", default="vsegpt", help="Provider prefix for env vars; default: vsegpt")
    parser.add_argument("--llm-base-url", default=None, help="OpenAI-compatible base URL; default: https://api.vsegpt.ru/v1")
    parser.add_argument("--llm-model", default=None, help="Model id from VseGPT Docs/Models, e.g. openai/gpt-4o-mini")
    parser.add_argument("--llm-temperature", type=float, default=None, help="LLM temperature; default: 0.01")
    parser.add_argument("--llm-max-tokens", type=int, default=None, help="Maximum generated tokens; default: 4000")
    parser.add_argument("--llm-timeout", type=float, default=None, help="HTTP timeout in seconds; default: 120")
    parser.add_argument("--llm-top-k", type=int, default=12, help="Candidate evidence snippets to send to the LLM")
    parser.add_argument("--no-response-format", action="store_true", help="Do not send VseGPT response_format=json_output")
    args = parser.parse_args(argv)
    load_env_file(args.env_file)

    llm_config = None
    if args.run_llm:
        try:
            llm_config = LLMConfig.from_env(
                provider=args.llm_provider,
                model=args.llm_model,
                base_url=args.llm_base_url,
                temperature=args.llm_temperature,
                max_tokens=args.llm_max_tokens,
                timeout_seconds=args.llm_timeout,
                use_response_format=not args.no_response_format,
            )
        except LLMConfigurationError:
            llm_config = None

    report = run_agent_check(
        args.source,
        output_dir=args.out,
        domain=args.domain,
        doc_id=args.doc_id,
        top_k=args.top_k,
        max_evidence=args.max_evidence,
        run_llm=args.run_llm,
        llm_config=llm_config,
        llm_top_k=args.llm_top_k,
    )
    print(f"Agent report: {report['artifacts']['json']}")
    print(f"Candidate evidence: {report['artifacts']['candidate_evidence_jsonl']}")
    if args.run_llm:
        print(f"LLM result: {report['artifacts']['llm_result_json']}")
    if report["skill_checks"]:
        best = report["skill_checks"][0]
        print(f"Top skill: {best['display_name']} ({best['status']}, score={best['score']})")


if __name__ == "__main__":
    main()
