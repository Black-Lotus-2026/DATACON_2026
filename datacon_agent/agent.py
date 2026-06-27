from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

from datacon_agent.domains import NOT_DETECTED, DomainSpec
from datacon_agent.normalize import finalize_samples
from datacon_agent.pdf import DocumentContext, PageContext, load_pdf
from datacon_agent.schema import fields_markdown, structured_output_schema


@dataclass
class AgentSettings:
    model: str = "gpt-4.1"
    review_model: str | None = None
    base_url: str | None = None
    temperature: float = 0.0
    pages_per_window: int = 4
    render_pages: bool = True
    max_image_pages_per_window: int = 4
    page_dpi: int = 160
    review_candidates: bool = True
    max_pages: int | None = None


class ChemExtractionAgent:
    def __init__(
        self,
        domain: DomainSpec,
        *,
        settings: AgentSettings | None = None,
        client: OpenAI | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.domain = domain
        self.settings = settings or AgentSettings()
        effective_base_url = base_url or self.settings.base_url or os.getenv("OPENAI_BASE_URL")
        self.client = client or OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            base_url=effective_base_url,
        )

    def extract_pdf(self, pdf_path: str | Path) -> list[dict[str, Any]]:
        document = load_pdf(
            pdf_path,
            render_pages=self.settings.render_pages,
            dpi=self.settings.page_dpi,
        )
        if self.settings.max_pages is not None:
            document.pages[:] = document.pages[: self.settings.max_pages]
        return self.extract_document(document)

    def extract_document(self, document: DocumentContext) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        windows = document.windows(pages_per_window=self.settings.pages_per_window)
        for window_index, pages in enumerate(windows, start=1):
            payload = self.extract_window(
                pages,
                pdf_name=document.pdf_path.name,
                window_index=window_index,
                window_count=len(windows),
            )
            candidates.extend(payload.get("samples", []))

        if not candidates:
            return []
        if not self.settings.review_candidates:
            return finalize_samples(self.domain, {"samples": candidates})

        reviewed = self.review(candidates, pdf_name=document.pdf_path.name)
        return finalize_samples(self.domain, reviewed)

    def extract_window(
        self,
        pages: list[PageContext],
        *,
        pdf_name: str,
        window_index: int,
        window_count: int,
    ) -> dict[str, Any]:
        prompt = self.window_prompt(
            pages,
            pdf_name=pdf_name,
            window_index=window_index,
            window_count=window_count,
        )
        content = self.content_with_images(pages, prompt)
        return self.chat_json(
            model=self.settings.model,
            messages=[
                {"role": "system", "content": self.system_prompt()},
                {"role": "user", "content": content},
            ],
            schema=structured_output_schema(self.domain, include_evidence=True),
            schema_name=f"{self.domain.key}_candidate_rows",
        )

    def review(self, candidates: list[dict[str, Any]], *, pdf_name: str) -> dict[str, Any]:
        review_prompt = self.review_prompt(candidates, pdf_name=pdf_name)
        return self.chat_json(
            model=self.settings.review_model or self.settings.model,
            messages=[
                {"role": "system", "content": self.system_prompt()},
                {"role": "user", "content": review_prompt},
            ],
            schema=structured_output_schema(self.domain, include_evidence=False),
            schema_name=f"{self.domain.key}_final_rows",
        )

    def chat_json(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        schema_name: str,
    ) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=self.settings.temperature,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                },
            },
        )
        content = response.choices[0].message.content
        if not content:
            return {"samples": []}
        payload = json.loads(content)
        if isinstance(payload, list):
            return {"samples": payload}
        return payload

    def content_with_images(self, pages: list[PageContext], prompt: str) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if not self.settings.render_pages:
            return content
        image_pages = [page for page in pages if page.image_jpeg is not None]
        for page in image_pages[: self.settings.max_image_pages_per_window]:
            encoded = base64.b64encode(page.image_jpeg or b"").decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{encoded}",
                        "detail": "high",
                    },
                }
            )
        return content

    def system_prompt(self) -> str:
        return (
            "You are a rigorous chemical information extraction agent. "
            "Extract only facts supported by the supplied article text, tables, or page images. "
            "Do not infer missing numeric values. Do not use prior knowledge to fill article facts. "
            f"Use {NOT_DETECTED!r} for fields that are absent after checking the evidence. "
            "Preserve reported names, units, organisms, and identifiers as closely as possible. "
            "Return only JSON matching the requested schema."
        )

    def window_prompt(
        self,
        pages: list[PageContext],
        *,
        pdf_name: str,
        window_index: int,
        window_count: int,
    ) -> str:
        page_text = "\n\n".join(page.as_text() for page in pages)
        return (
            f"PDF: {pdf_name}\n"
            f"Window: {window_index} of {window_count}\n\n"
            f"Domain: {self.domain.title}\n"
            f"Task: {self.domain.task}\n\n"
            "Extract rows only from the pages in this window. Page images are attached after "
            "the text and may contain structures, tables, plots, captions, or values missing "
            "from text extraction.\n\n"
            "Fields:\n"
            f"{fields_markdown(self.domain)}\n\n"
            f"{self.domain_guidance()}"
            "Rules:\n"
            "- Extract every distinct experimental record described by the task.\n"
            "- Keep repeated measurements as separate rows when the article reports them separately.\n"
            "- Do not collapse rows across different organisms, compounds, drugs, materials, assays, or conditions.\n"
            "- Use exact numeric values; do not convert units unless the field explicitly requires a fixed unit.\n"
            "- If a value is in a table image, read it from the image and cite the table or page in _evidence.\n"
            f"- Use {NOT_DETECTED!r} when a required field is not present in this window.\n\n"
            "Article window:\n"
            f"{page_text}"
        )

    def review_prompt(self, candidates: list[dict[str, Any]], *, pdf_name: str) -> str:
        candidate_json = json.dumps({"samples": candidates}, ensure_ascii=False, indent=2)
        return (
            f"PDF: {pdf_name}\n"
            f"Domain: {self.domain.title}\n"
            f"Task: {self.domain.task}\n\n"
            "You are reviewing candidate extraction rows produced from page windows of one article. "
            "Return the final extraction table.\n\n"
            "Fields:\n"
            f"{fields_markdown(self.domain)}\n\n"
            f"{self.domain_guidance()}"
            "Review rules:\n"
            "- Keep rows supported by evidence and remove rows that are clearly unrelated to the task.\n"
            "- Merge complementary partial rows that describe the same experimental record; prefer one complete row over several fragments.\n"
            "- Do not remove a row solely because another row has identical values; articles can report repeated measurements.\n"
            "- Remove rows that only describe general methods, setup conditions, literature controls, or comparison/reference materials when they are not target records.\n"
            "- Preserve exact strings and units from the candidates unless a field name or missing marker needs normalization.\n"
            f"- Use {NOT_DETECTED!r} for unresolved missing values.\n"
            "- Remove helper fields such as _evidence and _page from the final JSON.\n\n"
            "Candidate rows:\n"
            f"{candidate_json}"
        )

    def domain_guidance(self) -> str:
        if not self.domain.guidance:
            return ""
        lines = "\n".join(f"- {item}" for item in self.domain.guidance)
        return f"Domain guidance:\n{lines}\n\n"
