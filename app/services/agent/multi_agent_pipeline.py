from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.services.agent.chemical_ocr_agent import ChemicalOCRAgent
from app.services.agent.data_image_agent import DataImageAnalysisAgent
from app.services.agent.llm import ChatCompletionsClient, LLMConfig, LLMConfigurationError, load_env_file


def run_multi_agent_pipeline(
    sqlite_path: Path,
    output_dir: Path,
    *,
    data_config: LLMConfig,
    chemical_config: LLMConfig,
    data_limit: int | None = None,
    chemical_limit: int | None = None,
    max_crops_per_figure: int = 12,
) -> dict:
    sqlite_path = _resolve_sqlite(sqlite_path)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    data_agent = DataImageAnalysisAgent(
        sqlite_path,
        output_dir,
        ChatCompletionsClient(data_config),
        limit=data_limit,
        max_crops_per_figure=max_crops_per_figure,
    )
    data_report = data_agent.run()

    chemical_agent = ChemicalOCRAgent(
        Path(data_report["artifact"]),
        output_dir,
        ChatCompletionsClient(chemical_config),
        limit=chemical_limit,
    )
    chemical_report = chemical_agent.run()

    summary = {
        "status": "completed",
        "pipeline": "scraper_sqlite -> data_image_analysis_agent -> chemical_ocr_agent",
        "sqlite_path": str(sqlite_path),
        "data_agent": {
            "work_items": data_report["work_items"],
            "completed": data_report["completed"],
            "failed": data_report["failed"],
            "artifact": data_report["artifact"],
            "model": data_config.public_dict(),
        },
        "chemical_ocr_agent": {
            "work_items": chemical_report["work_items"],
            "accepted": chemical_report["accepted"],
            "needs_review": chemical_report["needs_review"],
            "rejected": chemical_report["rejected"],
            "artifacts": chemical_report["artifacts"],
            "model": chemical_config.public_dict(),
        },
    }
    summary_path = output_dir / "multi_agent_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["artifact"] = str(summary_path)
    return summary


def _resolve_sqlite(source: Path) -> Path:
    source = source.expanduser().resolve()
    sqlite_path = source / "scrape.sqlite" if source.is_dir() else source
    if sqlite_path.suffix.lower() not in {".sqlite", ".db"} or not sqlite_path.exists():
        raise FileNotFoundError(f"Expected scrape.sqlite or its run directory, got {source}")
    return sqlite_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run scraper SQLite -> image/data agent -> chemical OCR agent.",
    )
    parser.add_argument("source", type=Path, help="Path to scrape.sqlite or a scraper run directory")
    parser.add_argument("--out", type=Path, default=Path("runs/multi-agent"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--llm-provider", default="vsegpt")
    parser.add_argument("--llm-base-url", default=None)
    parser.add_argument("--data-model", default=None, help="Vision-capable model for figure and label analysis")
    parser.add_argument("--chemical-model", default=None, help="Vision-capable model for crop-to-SMILES analysis")
    parser.add_argument("--temperature", type=float, default=0.01)
    parser.add_argument("--max-tokens", type=int, default=1800)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--data-limit", type=int, default=None, help="Maximum parent figures to analyze")
    parser.add_argument("--chemical-limit", type=int, default=None, help="Maximum mapped crops to analyze")
    parser.add_argument("--max-crops-per-figure", type=int, default=12)
    parser.add_argument("--no-response-format", action="store_true")
    args = parser.parse_args(argv)

    load_env_file(args.env_file)
    try:
        data_config = LLMConfig.from_env(
            provider=args.llm_provider,
            model=args.data_model,
            base_url=args.llm_base_url,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout_seconds=args.timeout,
            use_response_format=not args.no_response_format,
        )
        chemical_config = LLMConfig.from_env(
            provider=args.llm_provider,
            model=args.chemical_model or args.data_model,
            base_url=args.llm_base_url,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout_seconds=args.timeout,
            use_response_format=not args.no_response_format,
        )
    except LLMConfigurationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    try:
        summary = run_multi_agent_pipeline(
            args.source,
            args.out,
            data_config=data_config,
            chemical_config=chemical_config,
            data_limit=args.data_limit,
            chemical_limit=args.chemical_limit,
            max_crops_per_figure=args.max_crops_per_figure,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    print(f"Pipeline summary: {summary['artifact']}")
    print(f"Data analysis: {summary['data_agent']['artifact']}")
    print(f"Chemical OCR JSON: {summary['chemical_ocr_agent']['artifacts']['json']}")
    print(f"Chemical OCR CSV: {summary['chemical_ocr_agent']['artifacts']['csv']}")


if __name__ == "__main__":
    main()
