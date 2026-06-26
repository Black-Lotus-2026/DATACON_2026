from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


"""OCSR executor for detected chemical structure crops.

MolScribe output is saved only after basic crop checks, optional confidence
thresholding, and RDKit SMILES validation. This keeps weak scheme fragments out
of the RAG evidence index while preserving skip/failure metadata in SQLite.
"""


MOLSCRIBE_PROVIDER = "molscribe"
DEFAULT_HF_REPO = "yujieq/MolScribe"
DEFAULT_HF_FILES = (
    "swin_base_char_aux_1m680k.pth",
    "swin_base_char_aux_1m.pth",
)


def run_ocsr(
    db_path: Path,
    *,
    provider: str = MOLSCRIBE_PROVIDER,
    detector_provider: str | None = "decimer_segmentation",
    checkpoint: Path | None = None,
    hf_repo: str = DEFAULT_HF_REPO,
    hf_filename: str | None = None,
    limit: int | None = None,
    rerun: bool = False,
    batch_size: int = 8,
    device: str = "cpu",
    min_confidence: float = 0.0,
) -> dict[str, int]:
    """Run MolScribe over structure crops and store accepted SMILES evidence."""
    if provider != MOLSCRIBE_PROVIDER:
        raise ValueError("Only provider='molscribe' is implemented.")

    db_path = db_path.resolve()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        detections = _load_structure_detections(
            conn,
            detector_provider=detector_provider,
            limit=limit,
            rerun=rerun,
        )
        if not detections:
            return {"candidates": 0, "processed": 0, "recognized": 0, "skipped": 0, "failed": 0}

        usable = []
        skipped = 0
        for detection in detections:
            image_path = Path(detection["image_path"])
            ok, reason = _is_usable_crop(image_path)
            if ok:
                usable.append(detection)
            else:
                skipped += 1
                _record_ocsr_skip(conn, detection, provider, reason)

        if not usable:
            conn.commit()
            return {
                "candidates": len(detections),
                "processed": 0,
                "recognized": 0,
                "skipped": skipped,
                "failed": 0,
            }

        checkpoint_path = checkpoint or _download_molscribe_checkpoint(hf_repo, hf_filename)
        model = _load_molscribe_model(checkpoint_path, device=device)

        processed = 0
        recognized = 0
        failed = 0
        for start in range(0, len(usable), batch_size):
            batch = usable[start : start + batch_size]
            image_paths = [str(Path(row["image_path"])) for row in batch]
            try:
                outputs = model.predict_image_files(
                    image_paths,
                    return_atoms_bonds=False,
                    return_confidence=True,
                )
            except Exception as exc:  # noqa: BLE001 - keep batch failure visible in metadata.
                failed += len(batch)
                for detection in batch:
                    _record_ocsr_failure(conn, detection, provider, exc)
                continue

            for detection, output in zip(batch, outputs):
                processed += 1
                smiles = _clean_smiles(output.get("smiles"))
                if smiles:
                    confidence = _as_float(output.get("confidence"))
                    if confidence is not None and confidence < min_confidence:
                        skipped += 1
                        _record_ocsr_skip(
                            conn,
                            detection,
                            provider,
                            f"MolScribe confidence {confidence:.4f} is below threshold {min_confidence:.4f}.",
                        )
                        continue
                    ok, reason = _is_rdkit_valid_smiles(smiles)
                    if not ok:
                        skipped += 1
                        _record_ocsr_skip(conn, detection, provider, reason)
                        continue
                    recognized += 1
                    _record_ocsr_success(conn, detection, provider, smiles, output)
                else:
                    skipped += 1
                    _record_ocsr_skip(conn, detection, provider, "MolScribe returned an empty SMILES.")

        _mark_parent_ocsr_tasks(conn)
        conn.commit()
        return {
            "candidates": len(detections),
            "processed": processed,
            "recognized": recognized,
            "skipped": skipped,
            "failed": failed,
        }
    finally:
        conn.close()


def _load_structure_detections(
    conn: sqlite3.Connection,
    *,
    detector_provider: str | None,
    limit: int | None,
    rerun: bool,
) -> list[sqlite3.Row]:
    where = ["image_path IS NOT NULL"]
    params: list[Any] = []
    if detector_provider:
        where.append("provider = ?")
        params.append(detector_provider)
    if not rerun:
        where.append("(smiles IS NULL OR trim(smiles) = '')")

    sql = f"""
        SELECT *
        FROM structure_detections
        WHERE {' AND '.join(where)}
        ORDER BY page_number, parent_figure_id, detection_id
    """
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return list(conn.execute(sql, params))


def _is_usable_crop(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "crop file does not exist"
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for OCSR crop checks. Install requirements.txt.") from exc

    with Image.open(path) as image:
        width, height = image.size

    if width < 32 or height < 32:
        return False, f"crop is too small: {width}x{height}"
    if width * height < 2_000:
        return False, f"crop area is too small: {width}x{height}"
    if max(width / max(height, 1), height / max(width, 1)) > 7.5:
        return False, f"crop aspect ratio is too extreme: {width}x{height}"
    return True, ""


def _download_molscribe_checkpoint(hf_repo: str, hf_filename: str | None) -> Path:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub is required to download MolScribe checkpoints. "
            "Install optional visual dependencies with: pip install -r requirements-visual.txt"
        ) from exc

    filenames = (hf_filename,) if hf_filename else DEFAULT_HF_FILES
    errors = []
    for filename in filenames:
        if not filename:
            continue
        try:
            return Path(hf_hub_download(repo_id=hf_repo, filename=filename))
        except Exception as exc:  # noqa: BLE001 - try known upstream checkpoint names.
            errors.append(f"{filename}: {exc}")
    raise RuntimeError("Could not download a MolScribe checkpoint. Tried: " + " | ".join(errors))


def _load_molscribe_model(checkpoint: Path, *, device: str):
    try:
        import argparse as argparse_module
        import torch

        add_safe_globals = getattr(torch.serialization, "add_safe_globals", None)
        if add_safe_globals is not None:
            add_safe_globals([argparse_module.Namespace])

        from molscribe import MolScribe
    except ImportError as exc:
        raise RuntimeError(
            "MolScribe is not installed in this Python environment. "
            "Use the optional visual env and install: pip install -r requirements-visual.txt"
        ) from exc

    return MolScribe(str(checkpoint), device=device)


def _record_ocsr_success(
    conn: sqlite3.Connection,
    detection: sqlite3.Row,
    provider: str,
    smiles: str,
    output: dict[str, Any],
) -> None:
    confidence = _as_float(output.get("confidence"))
    output = {
        **output,
        "quality_flags": _smiles_quality_flags(smiles, confidence),
    }
    metadata = _metadata_with_ocsr(detection, provider, "completed", output)
    conn.execute(
        """
        UPDATE structure_detections
        SET smiles = ?, confidence = COALESCE(?, confidence), metadata_json = ?
        WHERE detection_id = ?
        """,
        (smiles, confidence, json.dumps(metadata, ensure_ascii=False), detection["detection_id"]),
    )
    _upsert_smiles_evidence(conn, detection, provider, smiles, confidence, metadata)


def _record_ocsr_skip(conn: sqlite3.Connection, detection: sqlite3.Row, provider: str, reason: str) -> None:
    metadata = _metadata_with_ocsr(detection, provider, "skipped", {"reason": reason})
    conn.execute(
        """
        UPDATE structure_detections
        SET metadata_json = ?
        WHERE detection_id = ?
        """,
        (json.dumps(metadata, ensure_ascii=False), detection["detection_id"]),
    )


def _record_ocsr_failure(conn: sqlite3.Connection, detection: sqlite3.Row, provider: str, exc: Exception) -> None:
    metadata = _metadata_with_ocsr(detection, provider, "failed", {"error": str(exc)})
    conn.execute(
        """
        UPDATE structure_detections
        SET metadata_json = ?
        WHERE detection_id = ?
        """,
        (json.dumps(metadata, ensure_ascii=False), detection["detection_id"]),
    )


def _metadata_with_ocsr(
    detection: sqlite3.Row,
    provider: str,
    status: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    metadata = _load_metadata(detection["metadata_json"])
    metadata["ocsr"] = {
        "provider": provider,
        "status": status,
        "output": _jsonable(payload),
    }
    return metadata


def _upsert_smiles_evidence(
    conn: sqlite3.Connection,
    detection: sqlite3.Row,
    provider: str,
    smiles: str,
    confidence: float | None,
    metadata: dict[str, Any],
) -> None:
    evidence_id = f"{detection['detection_id']}:smiles"
    conn.execute("DELETE FROM evidence_fts WHERE evidence_id = ?", (evidence_id,))
    conn.execute("DELETE FROM evidence_blocks WHERE evidence_id = ?", (evidence_id,))

    caption = metadata.get("caption", "")
    text = (
        f"Chemical structure SMILES: {smiles} | "
        f"crop: {detection['image_path']} | "
        f"parent figure: {detection['parent_figure_id']} | "
        f"caption: {caption}"
    )
    metadata_json = json.dumps(
        {
            "detection_id": detection["detection_id"],
            "task_id": detection["task_id"],
            "image_path": detection["image_path"],
            **metadata,
        },
        ensure_ascii=False,
    )
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
            detection["doc_id"],
            detection["file_id"],
            detection["page_number"],
            "chemical_structure_smiles",
            None,
            detection["parent_figure_id"],
            caption,
            text,
            detection["bbox_json"],
            metadata_json,
            provider,
            confidence,
        ),
    )
    conn.execute(
        """
        INSERT INTO evidence_fts (evidence_id, doc_id, source_type, text, caption, section)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (evidence_id, detection["doc_id"], "chemical_structure_smiles", text, caption, ""),
    )


def _mark_parent_ocsr_tasks(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT parent_figure_id, sum(CASE WHEN smiles IS NOT NULL AND trim(smiles) != '' THEN 1 ELSE 0 END) AS smiles_count
        FROM structure_detections
        GROUP BY parent_figure_id
        """
    )
    for row in rows:
        if row["smiles_count"]:
            status = "completed"
        else:
            status = "skipped"
        conn.execute(
            """
            UPDATE visual_tasks
            SET status = ?
            WHERE task_type = 'ocsr'
              AND target_id = ?
            """,
            (status, row["parent_figure_id"]),
        )


def _load_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw_metadata": raw}
    return value if isinstance(value, dict) else {"raw_metadata": value}


def _clean_smiles(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    smiles = value.strip()
    if not smiles or smiles.lower() in {"none", "null", "nan", "invalid", "<invalid>"}:
        return ""
    return smiles


def _smiles_quality_flags(smiles: str, confidence: float | None) -> list[str]:
    flags = []
    if confidence is not None and confidence < 0.5:
        flags.append("low_confidence")
    if "*" in smiles:
        flags.append("wildcard_or_r_group")
    if "." in smiles:
        flags.append("multiple_components_or_fragment")
    return flags


def _is_rdkit_valid_smiles(smiles: str) -> tuple[bool, str]:
    try:
        from rdkit import Chem
    except ImportError:
        return True, ""

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return False, "RDKit could not parse MolScribe SMILES."
    return True, ""


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return _jsonable(value.item())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OCSR over detected chemical structure crops.")
    parser.add_argument("sqlite", type=Path, help="Path to scrape.sqlite.")
    parser.add_argument("--provider", choices=[MOLSCRIBE_PROVIDER], default=MOLSCRIBE_PROVIDER)
    parser.add_argument("--detector-provider", default="decimer_segmentation")
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--hf-repo", default=DEFAULT_HF_REPO)
    parser.add_argument("--hf-filename", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--device", default="cpu", help="Torch device for MolScribe. CPU is the safest default.")
    parser.add_argument("--min-confidence", type=float, default=0.0)
    args = parser.parse_args()

    try:
        result = run_ocsr(
            args.sqlite,
            provider=args.provider,
            detector_provider=args.detector_provider,
            checkpoint=args.checkpoint,
            hf_repo=args.hf_repo,
            hf_filename=args.hf_filename,
            limit=args.limit,
            rerun=args.rerun,
            batch_size=args.batch_size,
            device=args.device,
            min_confidence=args.min_confidence,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"candidates={result['candidates']}")
    print(f"processed={result['processed']}")
    print(f"recognized={result['recognized']}")
    print(f"skipped={result['skipped']}")
    print(f"failed={result['failed']}")


if __name__ == "__main__":
    main()
