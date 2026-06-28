from __future__ import annotations

import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import fitz
import pandas as pd
import requests
from tqdm import tqdm

from datacon_agent.domains import NOT_DETECTED, DomainSpec

ARTICLE_ID_COLUMNS_BY_DOMAIN: dict[str, tuple[str, ...]] = {
    "eyedrops": ("pdf", "PMID", "doi", "title"),
}
MANIFEST_COLUMNS = ["doi", "pdf", "status", "source_url", "supplementary_pdfs"]
PDF_DOWNLOAD_TIMEOUT_SECONDS = 120.0
PDF_REQUEST_TIMEOUT = (10, 20)


@dataclass(frozen=True)
class ArticleRef:
    doi: str
    pdf_id: str


def load_open_access_articles(domain: DomainSpec) -> list[ArticleRef]:
    try:
        from datasets import load_dataset
    except Exception as exc:
        raise RuntimeError("Install with `uv sync --extra eval` to download ChemX PDFs.") from exc

    frame = load_dataset(domain.hf_dataset)["train"].to_pandas()
    if "access" in frame.columns:
        access_mask = frame["access"].astype(str).str.strip().isin({"1", "1.0", "true", "True"})
        frame = frame.loc[access_mask].copy()
    if frame.empty or "doi" not in frame.columns:
        return []

    rows: list[ArticleRef] = []
    seen: set[tuple[str, str]] = set()
    for _, row in frame.iterrows():
        doi = clean_text(row.get("doi"))
        pdf_id = article_id_for_download(domain, row)
        if doi == NOT_DETECTED or pdf_id == NOT_DETECTED:
            continue
        key = (doi, pdf_id)
        if key in seen:
            continue
        seen.add(key)
        rows.append(ArticleRef(doi=doi, pdf_id=pdf_id))
    return rows


def clean_text(value: Any) -> str:
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", NOT_DETECTED.lower()}:
        return NOT_DETECTED
    return text


def article_id_for_download(domain: DomainSpec, row: pd.Series) -> str:
    candidates = ARTICLE_ID_COLUMNS_BY_DOMAIN.get(domain.key, ("pdf",))
    for column in candidates:
        if column not in row.index:
            continue
        value = clean_text(row.get(column))
        if value != NOT_DETECTED:
            return value
    return NOT_DETECTED


def download_open_access_pdfs(
    domain: DomainSpec,
    output_dir: str | Path,
    *,
    limit: int | None = None,
    overwrite: bool = False,
    mailto: str | None = None,
    include_supplementary: bool = True,
) -> pd.DataFrame:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    articles = load_open_access_articles(domain)
    if limit is not None:
        articles = articles[:limit]

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": f"DataConAgent/0.1 ({'mailto:' + mailto if mailto else 'no-mailto'})",
            "Accept": "application/pdf,text/html,application/json;q=0.9,*/*;q=0.8",
        }
    )

    rows: list[dict[str, Any]] = []
    manifest_path = out_dir / "download_manifest.csv"
    for article in tqdm(articles, desc=f"Download {domain.key}"):
        target = out_dir / pdf_filename(domain, article.pdf_id)
        if target.exists() and not overwrite:
            rows.append(
                {
                    "doi": article.doi,
                    "pdf": target.name,
                    "status": "exists",
                    "source_url": "",
                    "supplementary_pdfs": 0,
                }
            )
            write_manifest(rows, manifest_path)
            continue

        source_url = ""
        status = "not_found"
        downloaded_candidates: list[str] = []
        for url in openalex_pdf_candidates(session, article.doi):
            if try_download_pdf(session, url, target):
                source_url = url
                downloaded_candidates.append(url)
                status = "downloaded"
                break
        supp_count = 0
        if status == "downloaded" and include_supplementary:
            supp_count = download_and_merge_supplements(
                session,
                article.doi,
                target,
                source_urls=downloaded_candidates,
            )
            if supp_count:
                status = "downloaded_with_supplementary"
        rows.append(
            {
                "doi": article.doi,
                "pdf": target.name,
                "status": status,
                "source_url": source_url,
                "supplementary_pdfs": supp_count,
            }
        )
        write_manifest(rows, manifest_path)

    return write_manifest(rows, manifest_path)


def write_manifest(rows: list[dict[str, Any]], path: Path) -> pd.DataFrame:
    manifest = pd.DataFrame(rows, columns=MANIFEST_COLUMNS)
    manifest.to_csv(path, index=False)
    return manifest


def pdf_filename(domain: DomainSpec, pdf_id: str) -> str:
    name = Path(pdf_id).name
    if name.lower().endswith(".pdf"):
        return name
    return f"{name}.pdf"


def openalex_pdf_candidates(session: requests.Session, doi: str) -> list[str]:
    url = f"https://api.openalex.org/works/https://doi.org/{quote(doi, safe='')}"
    try:
        response = session.get(url, timeout=20)
    except requests.RequestException:
        return []
    if not response.ok:
        return []

    data = response.json()
    candidates: list[str] = []
    primary = data.get("primary_location") or {}
    add_candidate(candidates, primary.get("pdf_url"))

    for location in data.get("locations") or []:
        add_candidate(candidates, location.get("pdf_url"))

    open_access = data.get("open_access") or {}
    add_candidate(candidates, open_access.get("oa_url"))
    return candidates


def download_and_merge_supplements(
    session: requests.Session,
    doi: str,
    target: Path,
    *,
    source_urls: list[str],
) -> int:
    supp_urls = supplementary_pdf_candidates(session, doi, source_urls=source_urls)
    if not supp_urls:
        return 0

    temp_paths: list[Path] = []
    try:
        for index, url in enumerate(supp_urls[:5], start=1):
            temp_path = target.with_name(f"{target.stem}__supp{index}.pdf")
            if try_download_pdf(session, url, temp_path):
                temp_paths.append(temp_path)
        if not temp_paths:
            return 0
        merge_pdfs(target, temp_paths)
        return len(temp_paths)
    finally:
        for path in temp_paths:
            path.unlink(missing_ok=True)


class LinkCollector(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        data = {key: value for key, value in attrs}
        href = data.get("href")
        if not href:
            return
        label = " ".join(str(value or "") for value in data.values())
        self.links.append((urljoin(self.base_url, href), label))


def supplementary_pdf_candidates(
    session: requests.Session,
    doi: str,
    *,
    source_urls: list[str],
) -> list[str]:
    landing_pages = landing_candidates(doi, source_urls)
    candidates: list[str] = []
    for landing in landing_pages:
        try:
            response = session.get(landing, timeout=30, allow_redirects=True)
        except requests.RequestException:
            continue
        if not response.ok or "html" not in response.headers.get("content-type", "").lower():
            continue
        collector = LinkCollector(response.url)
        collector.feed(response.text)
        for href, label in collector.links:
            combined = f"{href} {label}".lower()
            if not looks_like_supplementary_pdf(combined):
                continue
            add_candidate(candidates, href)
    return candidates


def landing_candidates(doi: str, source_urls: list[str]) -> list[str]:
    candidates = [f"https://doi.org/{doi}"]
    for url in source_urls:
        if "/articlepdf/" in url:
            add_candidate(candidates, url.replace("/articlepdf/", "/articlelanding/"))
        if "/content/articlepdf/" in url:
            add_candidate(candidates, url.replace("/content/articlepdf/", "/content/articlelanding/"))
    return candidates


def looks_like_supplementary_pdf(value: str) -> bool:
    if ".pdf" not in value:
        return False
    supplementary_markers = (
        "supplement",
        "suppdata",
        "supporting",
        "esi",
        "electronic supplementary",
    )
    return any(marker in value for marker in supplementary_markers)


def add_candidate(candidates: list[str], value: object) -> None:
    if not isinstance(value, str):
        return
    cleaned = value.strip()
    if cleaned and cleaned not in candidates:
        candidates.append(cleaned)


def try_download_pdf(session: requests.Session, url: str, target: Path) -> bool:
    started_at = time.monotonic()

    def timed_out() -> bool:
        return time.monotonic() - started_at > PDF_DOWNLOAD_TIMEOUT_SECONDS

    try:
        target.unlink(missing_ok=True)
        with session.get(url, timeout=PDF_REQUEST_TIMEOUT, stream=True, allow_redirects=True) as response:
            if not response.ok:
                return False
            content_type = response.headers.get("content-type", "").lower()
            chunks: list[bytes] = []
            size = 0
            stream = response.iter_content(chunk_size=1024 * 128)
            for chunk in stream:
                if timed_out():
                    return False
                if chunk:
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= 1024 * 512:
                        break
            prefix = b"".join(chunks)
            if b"%PDF" not in prefix[:2048] and "pdf" not in content_type:
                return False
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as file:
                file.write(prefix)
                for chunk in stream:
                    if timed_out():
                        target.unlink(missing_ok=True)
                        return False
                    if chunk:
                        file.write(chunk)
            return target.stat().st_size > 1024
    except requests.RequestException:
        return False
    except OSError:
        return False


def merge_pdfs(target: Path, supplements: list[Path]) -> None:
    output = fitz.open()
    try:
        with fitz.open(target) as main:
            output.insert_pdf(main)
        for supplement in supplements:
            with fitz.open(supplement) as doc:
                output.insert_pdf(doc)
        merged = target.with_suffix(".merged.pdf")
        output.save(merged)
        merged.replace(target)
    finally:
        output.close()
