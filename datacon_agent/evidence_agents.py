from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datacon_agent.domains import NOT_DETECTED


AGENT_SOURCE_TYPES = (
    "agent_table_measurement",
    "agent_compound_link",
    "agent_conflict_decision",
    "agent_scaffold_resolution",
)


AGENT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_table_measurements (
  record_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  page_number INTEGER,
  table_id TEXT,
  evidence_id TEXT,
  compound_id TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_relation TEXT,
  target_value TEXT,
  target_units TEXT,
  bacteria TEXT,
  raw_text TEXT NOT NULL,
  confidence REAL,
  metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_compound_links (
  link_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  page_number INTEGER,
  compound_id TEXT NOT NULL,
  measurement_record_id TEXT,
  smiles_evidence_id TEXT,
  smiles TEXT,
  canonical_smiles TEXT,
  bacteria TEXT,
  target_type TEXT,
  target_value TEXT,
  target_units TEXT,
  confidence REAL,
  status TEXT NOT NULL,
  issues_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_conflict_decisions (
  decision_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  page_number INTEGER,
  compound_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  reason TEXT NOT NULL,
  canonical_record_json TEXT NOT NULL,
  confidence REAL,
  metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_scaffold_resolutions (
  scaffold_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  page_number INTEGER,
  source_evidence_id TEXT,
  status TEXT NOT NULL,
  compound_range TEXT,
  variable_sites_json TEXT NOT NULL,
  reason TEXT NOT NULL,
  metadata_json TEXT NOT NULL
);
"""


TARGET_RE = re.compile(r"\b(MIC|pMIC|MIC50|MIC80|IC50|EC50|FIC|lgK|logK|Km|Vmax)\b", re.I)
REL_VALUE_RE = re.compile(
    r"(?P<rel><=|>=|=|<|>)?\s*"
    r"(?P<value>\d+(?:[\.,]\d+)?)\s*"
    r"(?P<units>µg\s*mL[−-]1|μg\s*mL[−-]1|ug\s*mL[−-]1|"
    r"µg/mL|μg/mL|ug/mL|mg/L|mg\s*L[−-]1|mM|µM|μM|uM|nM)?",
    re.I,
)
COMPOUND_RE = re.compile(
    r"\b(?:compound|cmpd|compd)?\s*([A-Za-z]?\d+[A-Za-z]?(?:[-.][A-Za-z0-9]+)?)\b",
    re.I,
)
BACTERIA_PATTERNS = (
    ("Staphylococcus aureus", re.compile(r"\b(?:S\.?\s*aureus|Staphylococcus\s+aureus)\b", re.I)),
    ("Escherichia coli", re.compile(r"\b(?:E\.?\s*coli|Escherichia\s+coli)\b", re.I)),
    ("Pseudomonas aeruginosa", re.compile(r"\b(?:P\.?\s*aeruginosa|Pseudomonas\s+aeruginosa)\b", re.I)),
    ("Bacillus subtilis", re.compile(r"\b(?:B\.?\s*subtilis|Bacillus\s+subtilis)\b", re.I)),
    ("Enterococcus faecalis", re.compile(r"\b(?:E\.?\s*faecalis|Enterococcus\s+faecalis)\b", re.I)),
)
SMILES_TEXT_RE = re.compile(r"(?:canonical_smiles|smiles)\s*[=:]\s*([^|\s]+)", re.I)
COMPOUND_TEXT_RE = re.compile(r"compound_id\s*[=:]\s*([^|\s]+)", re.I)
SCAFFOLD_RE = re.compile(r"\b(scaffold|substituent|R\d+|R-group|R group)\b", re.I)
VARIABLE_SITE_RE = re.compile(r"\bR\d?\b")


@dataclass(frozen=True)
class EvidenceAgentConfig:
    run_table_agent: bool = True
    run_linking_agent: bool = True
    run_conflict_resolver: bool = True
    run_scaffold_resolver: bool = True


def run_evidence_agents(
    sqlite_path: str | Path,
    *,
    config: EvidenceAgentConfig | None = None,
) -> dict[str, Any]:
    cfg = config or EvidenceAgentConfig()
    db_path = Path(sqlite_path).expanduser().resolve()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        ensure_agent_schema(conn)
        summary: dict[str, Any] = {"sqlite_path": str(db_path)}
        if cfg.run_table_agent:
            summary["table_measurement_agent"] = TableMeasurementAgent(conn).run()
        if cfg.run_scaffold_resolver:
            summary["scaffold_resolver_agent"] = ScaffoldResolverAgent(conn).run()
        if cfg.run_linking_agent:
            summary["compound_linking_agent"] = CompoundLinkingAgent(conn).run()
        if cfg.run_conflict_resolver:
            summary["conflict_resolver_agent"] = ConflictResolverAgent(conn).run()
        conn.commit()
        return summary
    finally:
        conn.close()


def ensure_agent_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(AGENT_SCHEMA_SQL)


class TableMeasurementAgent:
    name = "table_measurement_agent"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def run(self) -> dict[str, int]:
        self._clear_previous()
        inserted = 0
        skipped = 0
        for row in self._rows():
            record = self._extract_record(row)
            if record is None:
                skipped += 1
                continue
            self._insert_record(record)
            inserted += 1
        return {"inserted": inserted, "skipped": skipped}

    def _rows(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT
                  tr.row_id,
                  tr.table_id,
                  tr.evidence_id,
                  tr.row_index,
                  tr.cells_json,
                  tr.normalized_text,
                  t.doc_id,
                  t.file_id,
                  t.page_number,
                  t.label,
                  t.caption,
                  t.columns_json
                FROM table_rows AS tr
                JOIN tables AS t ON t.table_id = tr.table_id
                ORDER BY t.page_number, tr.table_id, tr.row_index
                """
            )
        )

    def _extract_record(self, row: sqlite3.Row) -> dict[str, Any] | None:
        cells = json_list(row["cells_json"])
        columns = json_list(row["columns_json"])
        text = " | ".join(part for part in [row["caption"], row["normalized_text"]] if part)
        target_type = detect_target_type(text, columns)
        compound_id = detect_compound_id(cells, text)
        relation, value, units = detect_relation_value_units(text)
        if not target_type or not compound_id or value is None:
            return None
        bacteria = detect_bacteria(text)
        record_id = stable_id("tm", row["evidence_id"], compound_id, target_type, value, units or "")
        metadata = {
            "agent": self.name,
            "row_id": row["row_id"],
            "row_index": row["row_index"],
            "columns": columns,
            "cells": cells,
            "table_label": row["label"],
            "table_caption": row["caption"],
        }
        return {
            "record_id": record_id,
            "doc_id": row["doc_id"],
            "file_id": row["file_id"],
            "page_number": row["page_number"],
            "table_id": row["table_id"],
            "evidence_id": row["evidence_id"],
            "compound_id": compound_id,
            "target_type": target_type,
            "target_relation": relation or "=",
            "target_value": value,
            "target_units": units or NOT_DETECTED,
            "bacteria": bacteria or NOT_DETECTED,
            "raw_text": text,
            "confidence": table_measurement_confidence(compound_id, target_type, value, units, bacteria),
            "metadata": metadata,
        }

    def _insert_record(self, record: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO agent_table_measurements (
              record_id, doc_id, file_id, page_number, table_id, evidence_id,
              compound_id, target_type, target_relation, target_value,
              target_units, bacteria, raw_text, confidence, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["record_id"],
                record["doc_id"],
                record["file_id"],
                record["page_number"],
                record["table_id"],
                record["evidence_id"],
                record["compound_id"],
                record["target_type"],
                record["target_relation"],
                record["target_value"],
                record["target_units"],
                record["bacteria"],
                record["raw_text"],
                record["confidence"],
                json.dumps(record["metadata"], ensure_ascii=False),
            ),
        )
        text = (
            f"Agent table measurement: compound_id={record['compound_id']} | "
            f"target_type={record['target_type']} | relation={record['target_relation']} | "
            f"target_value={record['target_value']} | target_units={record['target_units']} | "
            f"bacteria={record['bacteria']} | source_table={record['table_id']} | "
            f"source_evidence={record['evidence_id']} | raw={record['raw_text']}"
        )
        upsert_agent_evidence(
            self.conn,
            evidence_id=f"{record['record_id']}:evidence",
            doc_id=record["doc_id"],
            file_id=record["file_id"],
            page_number=record["page_number"],
            source_type="agent_table_measurement",
            title=record["table_id"],
            caption=record["compound_id"],
            text=text,
            parser=self.name,
            confidence=record["confidence"],
            metadata=record["metadata"],
        )

    def _clear_previous(self) -> None:
        clear_agent_outputs(self.conn, "agent_table_measurement", "agent_table_measurements")


class CompoundLinkingAgent:
    name = "compound_linking_agent"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def run(self) -> dict[str, int]:
        self._clear_previous()
        measurements = self._measurements()
        smiles_by_compound = self._smiles_by_compound()
        inserted = 0
        missing_smiles = 0
        for measurement in measurements:
            compound_id = measurement["compound_id"]
            smiles_records = smiles_by_compound.get(compound_id, [])
            if smiles_records:
                for smiles_record in smiles_records:
                    self._insert_link(measurement, smiles_record)
                    inserted += 1
            else:
                self._insert_link(measurement, None)
                inserted += 1
                missing_smiles += 1
        return {"inserted": inserted, "missing_smiles": missing_smiles}

    def _measurements(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT *
                FROM agent_table_measurements
                ORDER BY page_number, record_id
                """
            )
        )

    def _smiles_by_compound(self) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        rows = self.conn.execute(
            """
            SELECT evidence_id, doc_id, file_id, page_number, text, caption, metadata_json, confidence
            FROM evidence_blocks
            WHERE source_type = 'chemical_structure_smiles'
            ORDER BY page_number, evidence_id
            """
        )
        for row in rows:
            compound_id = extract_compound_id_from_smiles_evidence(row)
            if not compound_id:
                continue
            smiles = extract_smiles_from_text(row["text"])
            if not smiles:
                continue
            item = {
                "evidence_id": row["evidence_id"],
                "doc_id": row["doc_id"],
                "file_id": row["file_id"],
                "page_number": row["page_number"],
                "smiles": smiles,
                "canonical_smiles": canonicalize_smiles(smiles),
                "confidence": row["confidence"],
                "text": row["text"],
            }
            result.setdefault(compound_id, []).append(item)
        return result

    def _insert_link(self, measurement: sqlite3.Row, smiles_record: dict[str, Any] | None) -> None:
        issues = []
        status = "accepted"
        if smiles_record is None:
            issues.append("missing_structure_smiles")
            status = "needs_review"
        canonical_smiles = smiles_record["canonical_smiles"] if smiles_record else NOT_DETECTED
        smiles = smiles_record["smiles"] if smiles_record else NOT_DETECTED
        confidence = link_confidence(measurement, smiles_record)
        link_id = stable_id(
            "cl",
            measurement["record_id"],
            smiles_record["evidence_id"] if smiles_record else "missing",
        )
        metadata = {
            "agent": self.name,
            "measurement_record_id": measurement["record_id"],
            "measurement_evidence_id": measurement["evidence_id"],
            "smiles_evidence_id": smiles_record["evidence_id"] if smiles_record else None,
        }
        self.conn.execute(
            """
            INSERT INTO agent_compound_links (
              link_id, doc_id, file_id, page_number, compound_id,
              measurement_record_id, smiles_evidence_id, smiles, canonical_smiles,
              bacteria, target_type, target_value, target_units, confidence,
              status, issues_json, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                link_id,
                measurement["doc_id"],
                measurement["file_id"],
                measurement["page_number"],
                measurement["compound_id"],
                measurement["record_id"],
                smiles_record["evidence_id"] if smiles_record else None,
                smiles,
                canonical_smiles,
                measurement["bacteria"],
                measurement["target_type"],
                measurement["target_value"],
                measurement["target_units"],
                confidence,
                status,
                json.dumps(issues, ensure_ascii=False),
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
        text = (
            f"Agent compound link: compound_id={measurement['compound_id']} | "
            f"canonical_smiles={canonical_smiles} | target_type={measurement['target_type']} | "
            f"target_value={measurement['target_value']} | target_units={measurement['target_units']} | "
            f"bacteria={measurement['bacteria']} | status={status} | issues={','.join(issues) or 'none'} | "
            f"measurement_record_id={measurement['record_id']} | "
            f"smiles_evidence_id={smiles_record['evidence_id'] if smiles_record else NOT_DETECTED}"
        )
        upsert_agent_evidence(
            self.conn,
            evidence_id=f"{link_id}:evidence",
            doc_id=measurement["doc_id"],
            file_id=measurement["file_id"],
            page_number=measurement["page_number"],
            source_type="agent_compound_link",
            title=measurement["compound_id"],
            caption=status,
            text=text,
            parser=self.name,
            confidence=confidence,
            metadata=metadata | {"issues": issues},
        )

    def _clear_previous(self) -> None:
        clear_agent_outputs(self.conn, "agent_compound_link", "agent_compound_links")


class ConflictResolverAgent:
    name = "conflict_resolver_agent"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def run(self) -> dict[str, int]:
        self._clear_previous()
        inserted = 0
        needs_review = 0
        groups: dict[tuple[str, str, str, str, str], list[sqlite3.Row]] = {}
        for row in self._links():
            key = (
                row["compound_id"],
                row["target_type"] or "",
                row["target_value"] or "",
                row["target_units"] or "",
                row["bacteria"] or "",
            )
            groups.setdefault(key, []).append(row)
        for rows in groups.values():
            decision = self._decide(rows)
            if decision["decision"] != "accepted":
                needs_review += 1
            self._insert_decision(decision)
            inserted += 1
        return {"inserted": inserted, "needs_review": needs_review}

    def _links(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT *
                FROM agent_compound_links
                ORDER BY compound_id, target_type, target_value, confidence DESC
                """
            )
        )

    def _decide(self, rows: list[sqlite3.Row]) -> dict[str, Any]:
        best = max(rows, key=lambda row: row["confidence"] or 0.0)
        smiles_values = {row["canonical_smiles"] for row in rows if row["canonical_smiles"] != NOT_DETECTED}
        issues = []
        decision = "accepted"
        reason = "best supported linked compound record"
        confidence = best["confidence"] or 0.0
        if any(row["status"] != "accepted" for row in rows):
            issues.append("incomplete_link")
            decision = "needs_review"
            reason = "one or more candidate links are incomplete"
            confidence = min(confidence, 0.62)
        if len(smiles_values) > 1:
            issues.append("conflicting_smiles")
            decision = "needs_review"
            reason = "multiple canonical SMILES candidates for the same measurement"
            confidence = min(confidence, 0.55)
        canonical = {
            "compound_id": best["compound_id"],
            "smiles": best["canonical_smiles"],
            "target_type": best["target_type"],
            "target_value": best["target_value"],
            "target_units": best["target_units"],
            "bacteria": best["bacteria"],
            "source_link_id": best["link_id"],
            "issues": issues,
        }
        return {
            "decision_id": stable_id("cr", best["compound_id"], best["target_type"], best["target_value"], best["target_units"], best["bacteria"]),
            "doc_id": best["doc_id"],
            "file_id": best["file_id"],
            "page_number": best["page_number"],
            "compound_id": best["compound_id"],
            "decision": decision,
            "reason": reason,
            "canonical": canonical,
            "confidence": confidence,
            "metadata": {
                "agent": self.name,
                "candidate_link_ids": [row["link_id"] for row in rows],
            },
        }

    def _insert_decision(self, decision: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO agent_conflict_decisions (
              decision_id, doc_id, file_id, page_number, compound_id, decision,
              reason, canonical_record_json, confidence, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision["decision_id"],
                decision["doc_id"],
                decision["file_id"],
                decision["page_number"],
                decision["compound_id"],
                decision["decision"],
                decision["reason"],
                json.dumps(decision["canonical"], ensure_ascii=False),
                decision["confidence"],
                json.dumps(decision["metadata"], ensure_ascii=False),
            ),
        )
        canonical = decision["canonical"]
        text = (
            f"Agent conflict decision: compound_id={canonical['compound_id']} | "
            f"decision={decision['decision']} | reason={decision['reason']} | "
            f"canonical_smiles={canonical['smiles']} | target_type={canonical['target_type']} | "
            f"target_value={canonical['target_value']} | target_units={canonical['target_units']} | "
            f"bacteria={canonical['bacteria']} | issues={','.join(canonical['issues']) or 'none'}"
        )
        upsert_agent_evidence(
            self.conn,
            evidence_id=f"{decision['decision_id']}:evidence",
            doc_id=decision["doc_id"],
            file_id=decision["file_id"],
            page_number=decision["page_number"],
            source_type="agent_conflict_decision",
            title=decision["compound_id"],
            caption=decision["decision"],
            text=text,
            parser=self.name,
            confidence=decision["confidence"],
            metadata=decision["metadata"] | {"canonical": canonical},
        )

    def _clear_previous(self) -> None:
        clear_agent_outputs(self.conn, "agent_conflict_decision", "agent_conflict_decisions")


class ScaffoldResolverAgent:
    name = "scaffold_resolver_agent"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def run(self) -> dict[str, int]:
        self._clear_previous()
        inserted = 0
        for row in self._candidate_evidence():
            text = " | ".join(str(part or "") for part in [row["caption"], row["title"], row["text"]])
            if not SCAFFOLD_RE.search(text):
                continue
            variable_sites = sorted(set(VARIABLE_SITE_RE.findall(text)))
            status = "needs_review" if variable_sites else "detected"
            reason = (
                "scaffold or R-group evidence detected; substituent assembly is not automated yet"
                if variable_sites
                else "scaffold-like evidence detected"
            )
            record = {
                "scaffold_id": stable_id("sr", row["evidence_id"], ",".join(variable_sites)),
                "doc_id": row["doc_id"],
                "file_id": row["file_id"],
                "page_number": row["page_number"],
                "source_evidence_id": row["evidence_id"],
                "status": status,
                "compound_range": detect_compound_range(text) or NOT_DETECTED,
                "variable_sites": variable_sites,
                "reason": reason,
                "metadata": {"agent": self.name, "source_type": row["source_type"], "source_text": row["text"]},
            }
            self._insert_record(record)
            inserted += 1
        return {"inserted": inserted}

    def _candidate_evidence(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT evidence_id, doc_id, file_id, page_number, source_type, title, caption, text
                FROM evidence_blocks
                WHERE page_number IS NOT NULL
                  AND source_type IN ('paragraph', 'table_caption', 'figure_caption', 'table_row', 'chemical_structure_smiles')
                ORDER BY page_number, evidence_id
                """
            )
        )

    def _insert_record(self, record: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO agent_scaffold_resolutions (
              scaffold_id, doc_id, file_id, page_number, source_evidence_id, status,
              compound_range, variable_sites_json, reason, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["scaffold_id"],
                record["doc_id"],
                record["file_id"],
                record["page_number"],
                record["source_evidence_id"],
                record["status"],
                record["compound_range"],
                json.dumps(record["variable_sites"], ensure_ascii=False),
                record["reason"],
                json.dumps(record["metadata"], ensure_ascii=False),
            ),
        )
        text = (
            f"Agent scaffold resolution: status={record['status']} | "
            f"compound_range={record['compound_range']} | "
            f"variable_sites={','.join(record['variable_sites']) or NOT_DETECTED} | "
            f"source_evidence={record['source_evidence_id']} | reason={record['reason']}"
        )
        upsert_agent_evidence(
            self.conn,
            evidence_id=f"{record['scaffold_id']}:evidence",
            doc_id=record["doc_id"],
            file_id=record["file_id"],
            page_number=record["page_number"],
            source_type="agent_scaffold_resolution",
            title=record["source_evidence_id"],
            caption=record["status"],
            text=text,
            parser=self.name,
            confidence=0.72 if record["variable_sites"] else 0.58,
            metadata=record["metadata"] | {"variable_sites": record["variable_sites"]},
        )

    def _clear_previous(self) -> None:
        clear_agent_outputs(self.conn, "agent_scaffold_resolution", "agent_scaffold_resolutions")


def clear_agent_outputs(conn: sqlite3.Connection, source_type: str, table_name: str) -> None:
    evidence_ids = [
        row[0]
        for row in conn.execute(
            "SELECT evidence_id FROM evidence_blocks WHERE source_type = ?",
            (source_type,),
        )
    ]
    if evidence_ids:
        placeholders = ",".join("?" for _ in evidence_ids)
        conn.execute(f"DELETE FROM evidence_fts WHERE evidence_id IN ({placeholders})", evidence_ids)
        conn.execute(f"DELETE FROM evidence_blocks WHERE evidence_id IN ({placeholders})", evidence_ids)
    conn.execute(f"DELETE FROM {table_name}")


def upsert_agent_evidence(
    conn: sqlite3.Connection,
    *,
    evidence_id: str,
    doc_id: str,
    file_id: str,
    page_number: int | None,
    source_type: str,
    title: str | None,
    caption: str | None,
    text: str,
    parser: str,
    confidence: float | None,
    metadata: dict[str, Any],
) -> None:
    conn.execute("DELETE FROM evidence_fts WHERE evidence_id = ?", (evidence_id,))
    conn.execute("DELETE FROM evidence_blocks WHERE evidence_id = ?", (evidence_id,))
    metadata_json = json.dumps(metadata, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO evidence_blocks (
          evidence_id, doc_id, file_id, page_number, source_type, section, title,
          caption, text, bbox_json, metadata_json, parser, confidence
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evidence_id,
            doc_id,
            file_id,
            page_number,
            source_type,
            "agent_evidence",
            title,
            caption,
            text,
            None,
            metadata_json,
            parser,
            confidence,
        ),
    )
    conn.execute(
        """
        INSERT INTO evidence_fts (evidence_id, doc_id, source_type, text, caption, section)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (evidence_id, doc_id, source_type, text, caption or "", "agent_evidence"),
    )


def detect_target_type(text: str, columns: list[str]) -> str | None:
    combined = " | ".join([text, *columns])
    match = TARGET_RE.search(combined)
    return match.group(1).upper() if match else None


def detect_compound_id(cells: list[str], text: str) -> str | None:
    for cell in cells[:2]:
        match = COMPOUND_RE.search(cell)
        if match:
            return match.group(1)
    match = COMPOUND_RE.search(text)
    return match.group(1) if match else None


def detect_relation_value_units(text: str) -> tuple[str | None, str | None, str | None]:
    for match in REL_VALUE_RE.finditer(text):
        value = match.group("value")
        if value is None:
            continue
        start = max(0, match.start() - 30)
        context = text[start : match.end() + 30]
        if TARGET_RE.search(context) or match.group("units"):
            return match.group("rel"), value.replace(",", "."), normalize_unit(match.group("units"))
    return None, None, None


def detect_bacteria(text: str) -> str | None:
    for label, pattern in BACTERIA_PATTERNS:
        if pattern.search(text):
            return label
    return None


def detect_compound_range(text: str) -> str | None:
    match = re.search(r"\b([A-Za-z]?\d+[A-Za-z]?)\s*[-–]\s*([A-Za-z]?\d+[A-Za-z]?)\b", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return None


def normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    cleaned = unit.strip()
    replacements = {
        "ug": "µg",
        "μ": "µ",
        "mL-1": "mL−1",
    }
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    return cleaned


def table_measurement_confidence(
    compound_id: str,
    target_type: str,
    value: str,
    units: str | None,
    bacteria: str | None,
) -> float:
    score = 0.58
    if compound_id:
        score += 0.1
    if target_type:
        score += 0.1
    if value:
        score += 0.1
    if units:
        score += 0.07
    if bacteria:
        score += 0.05
    return min(score, 0.95)


def link_confidence(measurement: sqlite3.Row, smiles_record: dict[str, Any] | None) -> float:
    score = 0.54
    if smiles_record:
        score += 0.25
        if smiles_record.get("confidence") is not None:
            score += min(float(smiles_record["confidence"]), 1.0) * 0.08
    if measurement["bacteria"] != NOT_DETECTED:
        score += 0.05
    if measurement["target_units"] != NOT_DETECTED:
        score += 0.04
    return min(score, 0.96)


def extract_compound_id_from_smiles_evidence(row: sqlite3.Row) -> str | None:
    metadata = load_json_object(row["metadata_json"])
    for key_path in (
        ("compound_id",),
        ("chemical_agent_record", "compound_id"),
        ("chemical_agent_record", "compound_id"),
    ):
        value = nested_get(metadata, key_path)
        if isinstance(value, str) and value.strip():
            return value.strip()
    text_match = COMPOUND_TEXT_RE.search(row["text"] or "")
    if text_match:
        return text_match.group(1).strip()
    caption = row["caption"]
    if isinstance(caption, str) and caption.strip() and caption.strip() != NOT_DETECTED:
        if COMPOUND_RE.fullmatch(caption.strip()) or re.fullmatch(r"[A-Za-z]?\d+[A-Za-z]?", caption.strip()):
            return caption.strip()
    return None


def extract_smiles_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = SMILES_TEXT_RE.search(text)
    if match:
        return match.group(1).strip()
    marker = "Chemical structure SMILES:"
    if marker in text:
        tail = text.split(marker, 1)[1].strip()
        return tail.split("|", 1)[0].strip()
    return None


def canonicalize_smiles(smiles: str) -> str:
    try:
        from rdkit import Chem
    except Exception:
        return smiles
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return smiles
    return Chem.MolToSmiles(mol, canonical=True)


def json_list(value: Any) -> list[str]:
    if value is None:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return [str(value)]
    if isinstance(parsed, list):
        return ["" if item is None else str(item) for item in parsed]
    return [str(parsed)]


def load_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def nested_get(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"
