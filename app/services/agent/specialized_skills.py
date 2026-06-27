from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


SPECIALIZED_SKILL_DIR = Path(__file__).resolve().parent / "skills" / "specialized"


@dataclass(frozen=True)
class SpecializedSkill:
    name: str
    description: str
    prompt: str
    source_path: str


def load_specialized_skill(name: str, *, skill_dir: Path = SPECIALIZED_SKILL_DIR) -> SpecializedSkill:
    path = skill_dir / name / "SKILL.md"
    if not path.exists():
        available = ", ".join(sorted(item.parent.name for item in skill_dir.glob("*/SKILL.md")))
        raise FileNotFoundError(f"Unknown specialized skill {name!r}. Available: {available or 'none'}")

    raw = path.read_text(encoding="utf-8")
    metadata, prompt = _split_frontmatter(raw)
    return SpecializedSkill(
        name=metadata.get("name", name),
        description=metadata.get("description", ""),
        prompt=prompt.strip(),
        source_path=str(path),
    )


def _split_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", raw, flags=re.S)
    if not match:
        return {}, raw

    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip():
            metadata[key.strip()] = value.strip()
    return metadata, raw[match.end() :]
