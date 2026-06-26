from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import deque
from pathlib import Path
from typing import Any


"""Executors for visual tasks stored by the scraper.

The default heuristic provider is lightweight and local. The optional DECIMER
provider gives better chemical structure crops and is intended to run in a
separate ML environment.
"""


HEURISTIC_PROVIDER = "structure_detector_heuristic"
DECIMER_PROVIDER = "decimer_segmentation"


def run_visual_tasks(
    db_path: Path,
    *,
    task_type: str = "chemical_structure_detection",
    limit: int | None = None,
    provider: str = "heuristic",
) -> dict[str, int]:
    """Run queued structure detection tasks and persist crop candidates."""
    if task_type != "chemical_structure_detection":
        raise ValueError("Only chemical_structure_detection is implemented in this executor.")
    if provider not in {"heuristic", "decimer"}:
        raise ValueError("provider must be one of: heuristic, decimer")

    db_path = db_path.resolve()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tasks = _load_tasks(conn, task_type, limit)
        if provider == "decimer":
            _assert_decimer_available()
        _clear_previous_structure_results(conn, [task["task_id"] for task in tasks])

        processed = 0
        detections = 0
        skipped = 0
        for task in tasks:
            if provider == "decimer":
                result_count = _run_decimer_structure_detection_task(conn, db_path.parent, task)
            else:
                result_count = _run_heuristic_structure_detection_task(conn, db_path.parent, task)
            processed += 1
            detections += result_count
            if result_count:
                conn.execute("UPDATE visual_tasks SET status = ? WHERE task_id = ?", ("completed", task["task_id"]))
            else:
                skipped += 1
                conn.execute("UPDATE visual_tasks SET status = ? WHERE task_id = ?", ("skipped", task["task_id"]))

        conn.commit()
        return {"processed": processed, "detections": detections, "skipped": skipped}
    finally:
        conn.close()


def _assert_decimer_available() -> None:
    try:
        import decimer_segmentation  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "DECIMER Segmentation is not installed in this Python environment. "
            "Recommended setup from upstream: conda create -n DECIMER_IMGSEG python=3.10; "
            "conda activate DECIMER_IMGSEG; pip install decimer-segmentation."
        ) from exc


def _load_tasks(conn: sqlite3.Connection, task_type: str, limit: int | None) -> list[sqlite3.Row]:
    sql = """
        SELECT *
        FROM visual_tasks
        WHERE task_type = ?
          AND status IN ('pending', 'skipped', 'completed')
        ORDER BY priority DESC, page_number, task_id
    """
    params: list[Any] = [task_type]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return list(conn.execute(sql, params))


def _clear_previous_structure_results(conn: sqlite3.Connection, task_ids: list[str]) -> None:
    if not task_ids:
        return
    placeholders = ",".join("?" for _ in task_ids)
    evidence_ids = [
        f"{row['detection_id']}:image"
        for row in conn.execute(
            f"""
            SELECT detection_id
            FROM structure_detections
            WHERE task_id IN ({placeholders})
            """,
            task_ids,
        )
    ]
    if evidence_ids:
        evidence_placeholders = ",".join("?" for _ in evidence_ids)
        conn.execute(f"DELETE FROM evidence_fts WHERE evidence_id IN ({evidence_placeholders})", evidence_ids)
        conn.execute(f"DELETE FROM evidence_blocks WHERE evidence_id IN ({evidence_placeholders})", evidence_ids)
    conn.execute(f"DELETE FROM structure_detections WHERE task_id IN ({placeholders})", task_ids)


def _run_decimer_structure_detection_task(conn: sqlite3.Connection, run_dir: Path, task: sqlite3.Row) -> int:
    try:
        from decimer_segmentation import segment_chemical_structures_from_file
    except ImportError as exc:
        raise RuntimeError(
            "DECIMER Segmentation is not installed in this Python environment. "
            "Recommended setup from upstream: conda create -n DECIMER_IMGSEG python=3.10; "
            "conda activate DECIMER_IMGSEG; pip install decimer-segmentation."
        ) from exc

    payload = json.loads(task["payload_json"])
    source_image = Path(payload["image_path"])
    if not source_image.exists():
        return 0

    segments = segment_chemical_structures_from_file(str(source_image), expand=True)
    structures_dir = run_dir / "images" / "structures" / _safe_dir_name(task["target_id"])
    structures_dir.mkdir(parents=True, exist_ok=True)
    for old_png in structures_dir.glob("*.png"):
        old_png.unlink()

    inserted = 0
    for index, segment in enumerate(segments, start=1):
        crop_path = structures_dir / f"decimer_structure_{index:03d}.png"
        _save_array_image(segment, crop_path)
        detection_id = f"{task['task_id']}:decimer:{index:04d}"
        metadata = {
            "source_image": str(source_image),
            "method": DECIMER_PROVIDER,
            "caption": payload.get("caption", ""),
            "kind": payload.get("kind", ""),
            "note": "DECIMER returns segmented structure crops; bbox in parent image is not provided by this API.",
        }
        _insert_structure_detection(
            conn=conn,
            task=task,
            detection_id=detection_id,
            crop_path=crop_path,
            bbox=None,
            metadata=metadata,
            provider=DECIMER_PROVIDER,
            confidence=0.82,
        )
        inserted += 1

    return inserted


def _run_heuristic_structure_detection_task(conn: sqlite3.Connection, run_dir: Path, task: sqlite3.Row) -> int:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for visual execution. Install dependencies with requirements.txt.") from exc

    payload = json.loads(task["payload_json"])
    source_image = Path(payload["image_path"])
    if not source_image.exists():
        return 0

    with Image.open(source_image) as image:
        rgb = image.convert("RGB")
        boxes = _detect_structure_boxes(rgb)

        structures_dir = run_dir / "images" / "structures" / _safe_dir_name(task["target_id"])
        structures_dir.mkdir(parents=True, exist_ok=True)
        for old_png in structures_dir.glob("*.png"):
            old_png.unlink()
        _save_debug_overlay(rgb, boxes, structures_dir / "_detections.png")

        inserted = 0
        for index, box in enumerate(boxes, start=1):
            crop = rgb.crop(box)
            crop_path = structures_dir / f"structure_{index:03d}.png"
            crop.save(crop_path)
            detection_id = f"{task['task_id']}:det:{index:04d}"
            metadata = {
                "source_image": str(source_image),
                "method": HEURISTIC_PROVIDER,
                "caption": payload.get("caption", ""),
                "kind": payload.get("kind", ""),
            }
            _insert_structure_detection(
                conn=conn,
                task=task,
                detection_id=detection_id,
                crop_path=crop_path,
                bbox=box,
                metadata=metadata,
                provider=HEURISTIC_PROVIDER,
                confidence=_box_confidence(box, rgb.size),
            )
            inserted += 1

    return inserted


def _save_array_image(image_array: Any, path: Path) -> None:
    try:
        import cv2

        cv2.imwrite(str(path), image_array)
        return
    except ImportError:
        pass

    from PIL import Image

    array = image_array
    if hasattr(array, "ndim") and array.ndim == 3 and array.shape[2] >= 3:
        array = array[:, :, :3][:, :, ::-1]
    Image.fromarray(array).save(path)


def _insert_structure_detection(
    *,
    conn: sqlite3.Connection,
    task: sqlite3.Row,
    detection_id: str,
    crop_path: Path,
    bbox: tuple[int, int, int, int] | None,
    metadata: dict[str, Any],
    provider: str,
    confidence: float,
) -> None:
    conn.execute(
        """
        INSERT INTO structure_detections (
          detection_id, task_id, doc_id, file_id, page_number, parent_figure_id,
          image_path, bbox_json, label_nearby, smiles, provider, confidence, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            detection_id,
            task["task_id"],
            task["doc_id"],
            task["file_id"],
            task["page_number"],
            task["target_id"],
            str(crop_path),
            json.dumps(bbox) if bbox else None,
            None,
            None,
            provider,
            confidence,
            json.dumps(metadata, ensure_ascii=False),
        ),
    )
    _insert_structure_evidence(conn, task, detection_id, crop_path, bbox, metadata, provider, confidence)


def _save_debug_overlay(image, boxes: list[tuple[int, int, int, int]], path: Path) -> None:
    from PIL import ImageDraw

    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    for index, box in enumerate(boxes, start=1):
        draw.rectangle(box, outline=(255, 0, 0), width=3)
        draw.text((box[0] + 4, box[1] + 4), str(index), fill=(255, 0, 0))
    overlay.save(path)


def _detect_structure_boxes(image) -> list[tuple[int, int, int, int]]:
    colored_boxes = _detect_boxes(image, _is_colored_ink, cell=8, min_ink=1, max_boxes=36)
    if _colored_boxes_are_useful(colored_boxes):
        return colored_boxes
    return _detect_boxes(image, _is_ink, cell=12, min_ink=2, max_boxes=24)


def _colored_boxes_are_useful(boxes: list[tuple[int, int, int, int]]) -> bool:
    large_boxes = [box for box in boxes if (box[2] - box[0]) >= 70 and (box[3] - box[1]) >= 55]
    return len(large_boxes) >= 2


def _detect_boxes(
    image,
    ink_predicate,
    *,
    cell: int,
    min_ink: int,
    max_boxes: int,
) -> list[tuple[int, int, int, int]]:
    width, height = image.size
    grid_w = (width + cell - 1) // cell
    grid_h = (height + cell - 1) // cell
    pixels = image.load()
    active: set[tuple[int, int]] = set()

    for gy in range(grid_h):
        y0 = gy * cell
        y1 = min(height, y0 + cell)
        for gx in range(grid_w):
            x0 = gx * cell
            x1 = min(width, x0 + cell)
            ink = 0
            for y in range(y0, y1, 2):
                for x in range(x0, x1, 2):
                    if ink_predicate(pixels[x, y]):
                        ink += 1
            if ink >= min_ink:
                active.add((gx, gy))

    components = _connected_components(active)
    boxes = []
    for component in components:
        x0 = min(gx for gx, _ in component) * cell
        y0 = min(gy for _, gy in component) * cell
        x1 = min(width, (max(gx for gx, _ in component) + 1) * cell)
        y1 = min(height, (max(gy for _, gy in component) + 1) * cell)
        refined = _refine_box(image, (x0, y0, x1, y1), ink_predicate)
        if refined and _keep_structure_box(refined, image.size):
            boxes.append(refined)

    boxes = _merge_nearby_boxes(boxes, image.size)
    return sorted(boxes, key=lambda box: (box[1], box[0]))[:max_boxes]


def _is_ink(pixel: tuple[int, int, int]) -> bool:
    r, g, b = pixel
    # Keep dark chemical/text strokes and colored annotations, ignore near-white background.
    if max(r, g, b) < 225:
        return True
    if min(r, g, b) < 180 and max(r, g, b) - min(r, g, b) > 30:
        return True
    return False


def _is_colored_ink(pixel: tuple[int, int, int]) -> bool:
    r, g, b = pixel
    if max(r, g, b) > 250:
        return False
    return max(r, g, b) - min(r, g, b) > 45


def _connected_components(active: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    components: list[set[tuple[int, int]]] = []
    remaining = set(active)
    while remaining:
        start = remaining.pop()
        component = {start}
        queue = deque([start])
        while queue:
            gx, gy = queue.popleft()
            for nx in range(gx - 1, gx + 2):
                for ny in range(gy - 1, gy + 2):
                    if (nx, ny) in remaining:
                        remaining.remove((nx, ny))
                        component.add((nx, ny))
                        queue.append((nx, ny))
        components.append(component)
    return components


def _refine_box(image, box: tuple[int, int, int, int], ink_predicate) -> tuple[int, int, int, int] | None:
    pixels = image.load()
    x0, y0, x1, y1 = box
    xs = []
    ys = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            if ink_predicate(pixels[x, y]):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    margin = 8
    return (
        max(0, min(xs) - margin),
        max(0, min(ys) - margin),
        min(image.size[0], max(xs) + margin),
        min(image.size[1], max(ys) + margin),
    )


def _keep_structure_box(box: tuple[int, int, int, int], size: tuple[int, int]) -> bool:
    width, height = size
    x0, y0, x1, y1 = box
    box_w = x1 - x0
    box_h = y1 - y0
    if box_w < 28 or box_h < 20:
        return False
    if box_w * box_h < 900:
        return False
    if box_w > width * 0.95 and box_h > height * 0.85:
        return False
    return True


def _merge_nearby_boxes(boxes: list[tuple[int, int, int, int]], size: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    merged = boxes[:]
    changed = True
    while changed:
        changed = False
        next_boxes: list[tuple[int, int, int, int]] = []
        used = [False] * len(merged)
        for index, box in enumerate(merged):
            if used[index]:
                continue
            current = box
            used[index] = True
            for other_index in range(index + 1, len(merged)):
                if used[other_index]:
                    continue
                other = merged[other_index]
                if _boxes_close(current, other):
                    current = (
                        min(current[0], other[0]),
                        min(current[1], other[1]),
                        max(current[2], other[2]),
                        max(current[3], other[3]),
                    )
                    used[other_index] = True
                    changed = True
            next_boxes.append(current)
        merged = [box for box in next_boxes if _keep_structure_box(box, size)]
    return merged


def _boxes_close(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    horizontal_gap = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    vertical_gap = max(0, max(a[1], b[1]) - min(a[3], b[3]))
    if horizontal_gap <= 10 and vertical_gap <= 10:
        return True
    if horizontal_gap <= 28 and _vertical_overlap_ratio(a, b) > 0.45:
        return True
    if vertical_gap <= 22 and _horizontal_overlap_ratio(a, b) > 0.45:
        return True
    return False


def _vertical_overlap_ratio(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    overlap = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return overlap / max(1, min(a[3] - a[1], b[3] - b[1]))


def _horizontal_overlap_ratio(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    return overlap / max(1, min(a[2] - a[0], b[2] - b[0]))


def _box_confidence(box: tuple[int, int, int, int], image_size: tuple[int, int]) -> float:
    image_area = image_size[0] * image_size[1]
    box_area = (box[2] - box[0]) * (box[3] - box[1])
    if box_area > image_area * 0.4:
        return 0.55
    if box_area > image_area * 0.08:
        return 0.72
    return 0.62


def _insert_structure_evidence(
    conn: sqlite3.Connection,
    task: sqlite3.Row,
    detection_id: str,
    crop_path: Path,
    box: tuple[int, int, int, int] | None,
    metadata: dict[str, Any],
    provider: str,
    confidence: float,
) -> None:
    evidence_id = f"{detection_id}:image"
    caption = metadata.get("caption", "")
    bbox_text = f"bbox: {box} | " if box else ""
    text = (
        f"Chemical structure candidate from {task['target_id']} | "
        f"crop: {crop_path} | {bbox_text}caption: {caption}"
    )
    metadata_json = json.dumps(
        {
            "task_id": task["task_id"],
            "detection_id": detection_id,
            "image_path": str(crop_path),
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
            task["doc_id"],
            task["file_id"],
            task["page_number"],
            "chemical_structure_image",
            None,
            task["target_id"],
            caption,
            text,
            json.dumps(box) if box else None,
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
        (evidence_id, task["doc_id"], "chemical_structure_image", text, caption, ""),
    )


def _safe_dir_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)[:160]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pending visual tasks from a scrape SQLite database.")
    parser.add_argument("sqlite", type=Path, help="Path to scrape.sqlite.")
    parser.add_argument("--task-type", default="chemical_structure_detection")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--provider", choices=["heuristic", "decimer"], default="heuristic")
    args = parser.parse_args()

    try:
        result = run_visual_tasks(args.sqlite, task_type=args.task_type, limit=args.limit, provider=args.provider)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"processed={result['processed']}")
    print(f"detections={result['detections']}")
    print(f"skipped={result['skipped']}")


if __name__ == "__main__":
    main()
