from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from datacon_agent.domains import ALIASES, NOT_DETECTED, DomainSpec

PDF_WITH_EXTENSION_DOMAINS = {"cytotoxicity", "seltox", "synergy", "magnetic"}
DECIMAL_INTEGER_FIELDS_BY_DOMAIN = {
    "nanozymes": {
        "c_min",
        "c_max",
        "c_const",
        "ccat_value",
        "ph",
        "temperature",
    },
}


def normalize_samples(domain: DomainSpec, payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_samples = payload.get("samples", []) if isinstance(payload, dict) else payload
    aliases = ALIASES.get(domain.key, {})
    rows: list[dict[str, Any]] = []

    for raw in raw_samples:
        if not isinstance(raw, dict):
            continue
        row: dict[str, Any] = {}
        for key, value in raw.items():
            target_key = aliases.get(key, key)
            if target_key in domain.columns:
                row[target_key] = normalize_field_value(domain, target_key, value)
        for column in domain.columns:
            row.setdefault(column, NOT_DETECTED)
        rows.append({column: row[column] for column in domain.columns})
    return rows


def finalize_samples(domain: DomainSpec, payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = normalize_samples(domain, payload)
    if domain.key == "nanozymes":
        rows = filter_nanozyme_setup_rows(rows)
    return rows


def filter_nanozyme_setup_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    has_kinetic_rows = any(
        not is_missing(row.get("km_value")) or not is_missing(row.get("vmax_value"))
        for row in rows
    )
    if not has_kinetic_rows:
        return rows
    return [
        row
        for row in rows
        if not (is_missing(row.get("km_value")) and is_missing(row.get("vmax_value")))
    ]


def is_missing(value: Any) -> bool:
    return value is None or value == "" or value == NOT_DETECTED


def normalize_value(value: Any) -> str | int | float:
    if value is None:
        return NOT_DETECTED
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return NOT_DETECTED
        if stripped.upper() in {"N/A", "NA", "NONE", "NULL", "NOT FOUND", "NOT_DETECTED"}:
            return NOT_DETECTED
        return canonicalize_text(stripped)
    return value


def normalize_field_value(domain: DomainSpec, field_name: str, value: Any) -> str | int | float:
    normalized = normalize_value(value)
    if field_name not in domain.numeric_fields or not isinstance(normalized, str):
        return normalized
    normalized = canonicalize_numeric_text(field_name, normalized)
    if field_name in DECIMAL_INTEGER_FIELDS_BY_DOMAIN.get(domain.key, set()):
        normalized = canonicalize_decimal_integer(normalized)
    return normalized


def canonicalize_numeric_text(field_name: str, value: str) -> str:
    lowered = value.lower()
    if field_name == "temperature" and lowered in {
        "room temperature",
        "rt",
        "ambient temperature",
        "not room temperature",
    }:
        return NOT_DETECTED

    cleaned = value
    for prefix in ("~", "≈", "about ", "ca. "):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    for separator in ("±", "+/-"):
        if separator in cleaned:
            cleaned = cleaned.split(separator, 1)[0].strip()
    scientific = parse_scientific_product(cleaned)
    if scientific is not None:
        return scientific
    return cleaned or NOT_DETECTED


def canonicalize_text(value: str) -> str:
    replacements = {
        "10^-": "10-",
        "10−": "10-",
        "s^-1": "s-1",
        "s⁻¹": "s-1",
        "min^-1": "min-1",
        "min⁻¹": "min-1",
        "μg mL^-1": "μg mL−1",
        "μg mL-1": "μg mL−1",
        "ug mL^-1": "μg mL−1",
        "ug mL-1": "μg mL−1",
        "µg mL^-1": "μg mL−1",
        "µg mL-1": "μg mL−1",
        "mg mL^-1": "mg mL−1",
        "mg mL-1": "mg mL−1",
        "α-": "",
        "α–": "",
        "alpha-": "",
    }
    normalized = value
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def parse_scientific_product(value: str) -> str | None:
    normalized = (
        value.replace("−", "-")
        .replace("⁻", "-")
        .replace("⁰", "0")
        .replace("¹", "1")
        .replace("²", "2")
        .replace("³", "3")
        .replace("⁴", "4")
        .replace("⁵", "5")
        .replace("⁶", "6")
        .replace("⁷", "7")
        .replace("⁸", "8")
        .replace("⁹", "9")
        .replace("^", "")
        .replace(" ", "")
    )
    for marker in ("×10", "x10", "*10"):
        if marker not in normalized:
            continue
        coefficient_text, exponent_text = normalized.split(marker, 1)
        try:
            coefficient = float(coefficient_text)
            exponent = int(exponent_text)
        except ValueError:
            return None
        return f"{coefficient * (10**exponent):.12g}"
    return None


def canonicalize_decimal_integer(value: str) -> str:
    text = value.strip()
    if not text or text == NOT_DETECTED:
        return value
    if "." in text or "e" in text.lower():
        return text

    unsigned = text[1:] if text[:1] in {"+", "-"} else text
    if not unsigned.isdigit():
        return text
    try:
        number = float(text)
    except ValueError:
        return text
    if not math.isfinite(number) or not number.is_integer():
        return text
    return f"{int(number)}.0"


def samples_to_frame(
    domain: DomainSpec,
    samples: list[dict[str, Any]],
    *,
    pdf_name: str | None = None,
) -> pd.DataFrame:
    rows = finalize_samples(domain, samples)
    frame = pd.DataFrame(rows, columns=domain.columns)
    if pdf_name is not None:
        frame["pdf"] = pdf_identifier(domain, pdf_name)
    return frame


def pdf_identifier(domain: DomainSpec, pdf_name: str) -> str:
    path = Path(pdf_name.strip())
    if domain.key in PDF_WITH_EXTENSION_DOMAINS:
        name = path.name
        if not name.lower().endswith(".pdf"):
            return f"{name}.pdf"
        return name
    return path.stem


def write_csv(
    domain: DomainSpec,
    samples: list[dict[str, Any]],
    output_path: str | Path,
    *,
    pdf_name: str | None = None,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = samples_to_frame(domain, samples, pdf_name=pdf_name)
    frame.to_csv(path, index=False)
    return path
