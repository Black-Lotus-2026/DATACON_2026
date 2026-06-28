from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image


@dataclass
class PageContext:
    number: int
    text: str
    tables: list[str] = field(default_factory=list)
    image_jpeg: bytes | None = None

    def as_text(self, *, include_tables: bool = True) -> str:
        parts = [f"PAGE {self.number}", self.text.strip()]
        if include_tables and self.tables:
            for idx, table in enumerate(self.tables, start=1):
                parts.append(f"TABLE {self.number}.{idx}\n{table}")
        return "\n\n".join(part for part in parts if part)


@dataclass
class DocumentContext:
    pdf_path: Path
    pages: list[PageContext]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def windows(self, *, pages_per_window: int) -> list[list[PageContext]]:
        if pages_per_window < 1:
            raise ValueError("pages_per_window must be positive")
        return [
            self.pages[start : start + pages_per_window]
            for start in range(0, len(self.pages), pages_per_window)
        ]


def load_pdf(
    pdf_path: str | Path,
    *,
    render_pages: bool = True,
    dpi: int = 160,
) -> DocumentContext:
    import fitz

    path = Path(pdf_path)
    doc = fitz.open(path)
    pages: list[PageContext] = []
    try:
        for page_index, page in enumerate(doc, start=1):
            text = page.get_text("text", sort=True)
            tables = extract_tables(page)
            image_jpeg = render_page(page, dpi=dpi) if render_pages else None
            pages.append(
                PageContext(
                    number=page_index,
                    text=text,
                    tables=tables,
                    image_jpeg=image_jpeg,
                )
            )
    finally:
        doc.close()
    return DocumentContext(pdf_path=path, pages=pages)


def extract_tables(page: fitz.Page) -> list[str]:
    if not hasattr(page, "find_tables"):
        return []
    try:
        found = page.find_tables()
    except Exception:
        return []

    tables: list[str] = []
    for table in getattr(found, "tables", []):
        try:
            rows = table.extract()
        except Exception:
            continue
        markdown = table_to_markdown(rows)
        if markdown:
            tables.append(markdown)
    return tables


def table_to_markdown(rows: list[list[object]]) -> str:
    cleaned: list[list[str]] = []
    width = 0
    for row in rows:
        values = [cell_to_text(cell) for cell in row]
        if any(values):
            cleaned.append(values)
            width = max(width, len(values))
    if not cleaned:
        return ""

    normalized = [row + [""] * (width - len(row)) for row in cleaned]
    header = normalized[0]
    separator = ["---"] * width
    body = normalized[1:]
    lines = [markdown_row(header), markdown_row(separator)]
    lines.extend(markdown_row(row) for row in body)
    return "\n".join(lines)


def markdown_row(row: list[str]) -> str:
    escaped = [value.replace("|", "/") for value in row]
    return "| " + " | ".join(escaped) + " |"


def cell_to_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").strip()


def render_page(page: fitz.Page, *, dpi: int) -> bytes:
    import fitz

    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    output = BytesIO()
    image.save(output, format="JPEG", quality=88, optimize=True)
    return output.getvalue()
