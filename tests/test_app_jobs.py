import io
import zipfile
from pathlib import Path

import pytest

from app.services.jobs import analyze_source


def test_zip_archive_with_pdf_is_analyzed() -> None:
    pdf_bytes = Path("pdf-dataset/antibiotics-12-01220-v2.pdf").read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("papers/article.pdf", pdf_bytes)
        archive.writestr("README.txt", "supporting file")

    result = analyze_source(buffer.getvalue(), "papers.zip")
    summary = result["summary"]

    assert summary["archive_files"] == 2
    assert summary["pdf_files"] == 1
    assert summary["analyzed_pdf_files"] == 1
    assert summary["source_documents"] == ["papers/article.pdf"]
    assert any("papers/article.pdf:" in note for note in summary["notes"])


def test_zip_archive_without_pdf_is_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("notes.txt", "no pdf here")

    with pytest.raises(ValueError, match="must contain at least one PDF"):
        analyze_source(buffer.getvalue(), "notes.zip")
