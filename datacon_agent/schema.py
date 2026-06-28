from __future__ import annotations

from datacon_agent.domains import DomainSpec


def structured_output_schema(domain: DomainSpec, *, include_evidence: bool = False) -> dict:
    properties: dict[str, dict] = {}
    required: list[str] = []
    for field in domain.fields:
        schema_type: list[str] = ["string", "number", "null"]
        field_schema: dict = {
            "type": schema_type,
            "description": field.description,
        }
        if field.enum:
            enum_values = list(field.enum)
            enum_values.append("NOT_DETECTED")
            field_schema["enum"] = enum_values
        properties[field.name] = field_schema
        required.append(field.name)

    if include_evidence:
        properties["_evidence"] = {
            "type": ["string", "null"],
            "description": "Short quote, table caption, or page-local evidence for this row.",
        }
        properties["_page"] = {
            "type": ["number", "null"],
            "description": "Most relevant page number using one-based page indexing.",
        }
        required.extend(["_evidence", "_page"])

    return {
        "type": "object",
        "properties": {
            "samples": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            }
        },
        "required": ["samples"],
        "additionalProperties": False,
    }


def fields_markdown(domain: DomainSpec) -> str:
    lines = []
    for field in domain.fields:
        enum_text = ""
        if field.enum:
            enum_text = f" Allowed values: {', '.join(field.enum)}."
        lines.append(f"- `{field.name}` ({field.kind}): {field.description}{enum_text}")
    return "\n".join(lines)
