from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().parent / "chemx_prompts"
UPSTREAM_PROMPT_URL = "https://github.com/ai-chem/ChemX/tree/main/LLM/data/prompts"


@dataclass(frozen=True)
class PromptVariant:
    name: str
    constant_name: str
    prompt: str
    expected_fields: tuple[str, ...]
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class ChemXSkill:
    name: str
    display_name: str
    instructions: str
    variants: tuple[PromptVariant, ...]
    expected_fields: tuple[str, ...]
    keywords: tuple[str, ...]
    source_path: str
    upstream_url: str


SKILL_LABELS = {
    "benzimidazole": "Benzimidazoles",
    "cocrystals": "Co-crystals",
    "complexes": "Complexes",
    "cytotoxicity": "Cytotox",
    "magnetic": "Nanomag",
    "nanozymes": "Nanozymes",
    "oxazolidinone": "Oxazolidinones",
    "seltox": "SelTox",
    "synergy": "Synergy",
}

DOMAIN_TO_SKILL = {
    "benzimidazoles": "benzimidazole",
    "benzimidazole": "benzimidazole",
    "co-crystals": "cocrystals",
    "cocrystals": "cocrystals",
    "co crystals": "cocrystals",
    "complexes": "complexes",
    "complex": "complexes",
    "cytotox": "cytotoxicity",
    "cytotoxicity": "cytotoxicity",
    "nanomag": "magnetic",
    "magnetic": "magnetic",
    "nanozymes": "nanozymes",
    "nanozyme": "nanozymes",
    "oxazolidinones": "oxazolidinone",
    "oxazolidinone": "oxazolidinone",
    "seltox": "seltox",
    "selective toxicity": "seltox",
    "synergy": "synergy",
}

CURATED_KEYWORDS = {
    "benzimidazole": (
        "benzimidazole",
        "MIC",
        "pMIC",
        "Staphylococcus",
        "aureus",
        "Escherichia",
        "coli",
        "antibacterial",
        "antibiotic",
    ),
    "cocrystals": (
        "cocrystal",
        "co-crystal",
        "coformer",
        "drug",
        "photostability",
        "solubility",
        "ratio",
    ),
    "complexes": (
        "organometallic",
        "complex",
        "chelate",
        "ligand",
        "logK",
        "lgK",
        "Ga",
        "Gd",
        "Tc",
        "Lu",
        "stability constant",
    ),
    "cytotoxicity": (
        "cytotoxicity",
        "viability",
        "cell",
        "concentration",
        "nanoparticle",
        "zeta",
        "hydrodynamic",
        "morphology",
    ),
    "magnetic": (
        "magnetic",
        "magnetization",
        "coercivity",
        "saturation",
        "MRI",
        "SAR",
        "hyperthermia",
        "nanoparticle",
        "squid",
    ),
    "nanozymes": (
        "nanozyme",
        "enzyme-like",
        "activity",
        "Km",
        "Vmax",
        "reaction",
        "pH",
        "temperature",
        "catalytic",
    ),
    "oxazolidinone": (
        "oxazolidinone",
        "MIC",
        "pMIC",
        "Staphylococcus",
        "aureus",
        "Escherichia",
        "coli",
        "antibacterial",
        "antibiotic",
    ),
    "seltox": (
        "silver",
        "AgNP",
        "toxicity",
        "antimicrobial",
        "bacteria",
        "zoi",
        "zone of inhibition",
        "zeta",
    ),
    "synergy": (
        "synergy",
        "FIC",
        "MIC",
        "antibiotic",
        "drug",
        "bacteria",
        "nanoparticle",
        "fold increase",
        "viability",
    ),
}

FIELD_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{3,}")
STOPWORDS = {
    "only",
    "from",
    "with",
    "that",
    "this",
    "your",
    "task",
    "output",
    "json",
    "array",
    "object",
    "objects",
    "string",
    "number",
    "value",
    "field",
    "fields",
    "must",
    "text",
    "article",
    "scientific",
    "extract",
    "every",
    "mention",
    "mentions",
}


def load_chemx_skills(prompt_dir: Path = PROMPT_DIR) -> dict[str, ChemXSkill]:
    skills: dict[str, ChemXSkill] = {}
    for path in sorted(prompt_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue

        constants = _read_string_constants(path)
        instructions = constants.get("INSTRUCTIONS", "")
        prompt_constants = {
            name: value
            for name, value in constants.items()
            if name == "PROMPT" or name.endswith("_PROMPT")
        }
        if not prompt_constants:
            continue

        skill_name = path.stem
        variants = []
        all_fields: list[str] = []
        for constant_name, prompt in prompt_constants.items():
            variant_name = "default" if constant_name == "PROMPT" else constant_name.removesuffix("_PROMPT").lower()
            fields = tuple(_ordered_unique(FIELD_RE.findall(prompt)))
            all_fields.extend(fields)
            variant_keywords = tuple(
                _ordered_unique(
                    [
                        *CURATED_KEYWORDS.get(skill_name, ()),
                        *_field_terms(fields),
                        *_prompt_keywords(prompt, limit=32),
                    ]
                )
            )
            variants.append(
                PromptVariant(
                    name=variant_name,
                    constant_name=constant_name,
                    prompt=prompt,
                    expected_fields=fields,
                    keywords=variant_keywords,
                )
            )

        expected_fields = tuple(_ordered_unique(all_fields))
        keywords = tuple(
            _ordered_unique(
                [
                    *CURATED_KEYWORDS.get(skill_name, ()),
                    *_field_terms(expected_fields),
                    *_prompt_keywords(instructions, limit=16),
                ]
            )
        )
        skills[skill_name] = ChemXSkill(
            name=skill_name,
            display_name=SKILL_LABELS.get(skill_name, skill_name.replace("_", " ").title()),
            instructions=instructions,
            variants=tuple(variants),
            expected_fields=expected_fields,
            keywords=keywords,
            source_path=str(path),
            upstream_url=f"{UPSTREAM_PROMPT_URL}/{path.name}",
        )

    return skills


def select_chemx_skills(domain: str | None, *, prompt_dir: Path = PROMPT_DIR) -> tuple[list[ChemXSkill], str | None]:
    skills = load_chemx_skills(prompt_dir)
    if not domain:
        return list(skills.values()), None

    skill_name = DOMAIN_TO_SKILL.get(_normalize_domain(domain))
    if not skill_name:
        return list(skills.values()), f"No ChemX prompt skill is mapped for domain '{domain}'. Ran all skills for sniffing."

    skill = skills.get(skill_name)
    if not skill:
        return list(skills.values()), f"Mapped skill '{skill_name}' for domain '{domain}' is missing locally. Ran all skills."
    return [skill], None


def _read_string_constants(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    constants: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (SyntaxError, ValueError):
            continue
        if not isinstance(value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value
    return constants


def _prompt_keywords(text: str, *, limit: int) -> list[str]:
    words = []
    for match in WORD_RE.finditer(text):
        word = match.group(0).strip("_")
        lowered = word.lower()
        if lowered in STOPWORDS or len(lowered) < 4:
            continue
        if word.isupper() or lowered not in STOPWORDS:
            words.append(word)
    return _ordered_unique(words)[:limit]


def _field_terms(fields: tuple[str, ...] | list[str]) -> list[str]:
    terms: list[str] = []
    for field in fields:
        terms.append(field)
        terms.extend(part for part in re.split(r"[_\W]+", field) if len(part) > 2)
    return terms


def _normalize_domain(domain: str) -> str:
    return " ".join(domain.strip().lower().replace("_", " ").split())


def _ordered_unique(values: list[str] | tuple[str, ...]) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        cleaned = value.strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered

