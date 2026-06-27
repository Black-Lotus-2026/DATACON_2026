from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from datacon_agent.agent import AgentSettings, ChemExtractionAgent
from datacon_agent.batch import extract_pdf_dir, review_prediction_csv
from datacon_agent.download import download_open_access_pdfs
from datacon_agent.domains import DOMAINS, get_domain
from datacon_agent.metrics import evaluate_predictions, macro_f1, read_article_ids
from datacon_agent.normalize import write_csv
from datacon_agent.schema import structured_output_schema
from datacon_agent.scraper_context import DEFAULT_SCRAPER_DIR, ScraperPipelineConfig, scrape_pdf_to_document


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="datacon-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    domains = subparsers.add_parser("domains", help="List supported ChemX domains")
    domains.set_defaults(func=cmd_domains)

    schema = subparsers.add_parser("schema", help="Print the structured output schema")
    schema.add_argument("--domain", required=True, choices=sorted(DOMAINS))
    schema.set_defaults(func=cmd_schema)

    extract = subparsers.add_parser("extract", help="Extract one PDF into ChemX-style CSV")
    add_agent_args(extract)
    add_scraper_args(extract)
    extract.add_argument("--pdf", required=True, help="Path to article PDF")
    extract.add_argument("--out", required=True, help="Output CSV path")
    extract.set_defaults(func=cmd_extract)

    batch = subparsers.add_parser("batch", help="Extract every PDF in a directory")
    add_agent_args(batch)
    add_scraper_args(batch)
    batch.add_argument("--pdf-dir", required=True, help="Directory with PDF files")
    batch.add_argument("--out", required=True, help="Output CSV path")
    batch.set_defaults(func=cmd_batch)

    review_csv = subparsers.add_parser(
        "review-csv",
        help="Refine a prediction CSV with article-level text context",
    )
    add_agent_args(review_csv)
    add_scraper_args(review_csv)
    review_csv.add_argument("--pred", required=True, help="Candidate prediction CSV")
    review_csv.add_argument("--pdf-dir", required=True, help="Directory with matching PDF files")
    review_csv.add_argument("--out", required=True, help="Reviewed output CSV path")
    review_csv.add_argument("--passes", type=int, default=1, help="Number of iterative review passes")
    review_csv.set_defaults(func=cmd_review_csv)

    download = subparsers.add_parser("download-pdfs", help="Download open-access PDFs by DOI")
    download.add_argument("--domain", required=True, choices=sorted(DOMAINS))
    download.add_argument("--out-dir", required=True, help="Directory for downloaded PDF files")
    download.add_argument("--limit", type=int, help="Maximum number of unique open-access PDFs")
    download.add_argument("--overwrite", action="store_true")
    download.add_argument("--mailto", help="Contact email for API User-Agent")
    download.add_argument("--no-supplementary", action="store_true", help="Skip supplementary PDF merge")
    download.set_defaults(func=cmd_download)

    evaluate = subparsers.add_parser("evaluate", help="Evaluate a prediction CSV")
    evaluate.add_argument("--domain", required=True, choices=sorted(DOMAINS))
    evaluate.add_argument("--pred", required=True, help="Prediction CSV")
    evaluate.add_argument("--truth-csv", help="Optional local truth CSV instead of Hugging Face")
    evaluate.add_argument("--articles", help="Optional newline-separated article id subset")
    evaluate.add_argument("--out", help="Optional metrics CSV output path")
    evaluate.set_defaults(func=cmd_evaluate)

    web = subparsers.add_parser("web", help="Run Streamlit interface")
    web.set_defaults(func=cmd_web)

    return parser


def add_agent_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--domain", required=True, choices=sorted(DOMAINS))
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--review-model")
    parser.add_argument("--base-url", help="OpenAI-compatible API base URL")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--pages-per-window", type=int, default=4)
    parser.add_argument("--max-image-pages-per-window", type=int, default=4)
    parser.add_argument("--page-dpi", type=int, default=160)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--no-images", action="store_true", help="Do not send rendered page images")
    parser.add_argument("--no-review", action="store_true", help="Skip final LLM review pass")
    parser.add_argument(
        "--review-context-chars",
        type=int,
        default=60_000,
        help="Maximum article text characters included in the final review pass; use 0 to disable",
    )


def add_scraper_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--use-scraper",
        action="store_true",
        help="Run the local SQLite evidence scraper before calling the LLM agent",
    )
    parser.add_argument(
        "--scrape-sqlite",
        help="Use an existing scrape.sqlite instead of rebuilding the scraper run. Supported for single-PDF extract.",
    )
    parser.add_argument(
        "--scraper-dir",
        default=str(DEFAULT_SCRAPER_DIR),
        help="Directory for scraper run artifacts",
    )
    parser.add_argument(
        "--overwrite-scrape",
        action="store_true",
        help="Rebuild scrape.sqlite even when a cached scrape exists",
    )
    parser.add_argument("--run-visual", action="store_true", help="Run structure detection before LLM extraction")
    parser.add_argument("--visual-provider", choices=["heuristic", "decimer"], default="heuristic")
    parser.add_argument("--visual-limit", type=int)
    parser.add_argument("--run-ocsr", action="store_true", help="Run MolScribe OCSR before LLM extraction")
    parser.add_argument("--ocsr-provider", choices=["molscribe"], default="molscribe")
    parser.add_argument(
        "--ocsr-detector-provider",
        default=None,
        help="Filter OCSR crops by detector provider, e.g. decimer_segmentation. Default uses all detections.",
    )
    parser.add_argument("--ocsr-limit", type=int)
    parser.add_argument("--ocsr-rerun", action="store_true")
    parser.add_argument("--ocsr-batch-size", type=int, default=8)
    parser.add_argument("--ocsr-device", default="cpu")
    parser.add_argument("--ocsr-min-confidence", type=float, default=0.0)
    parser.add_argument(
        "--run-chemical-agents",
        action="store_true",
        help="Run DataImageAnalysisAgent and ChemicalOCRAgent, then import accepted SMILES into scrape.sqlite",
    )
    parser.add_argument("--chemical-agent-dir", help="Root directory for old chemical-agent artifacts")
    parser.add_argument("--chemical-env-file", default=".env")
    parser.add_argument("--chemical-llm-provider", default="vsegpt")
    parser.add_argument("--chemical-llm-base-url")
    parser.add_argument("--chemical-data-model", help="Vision-capable model for DataImageAnalysisAgent")
    parser.add_argument("--chemical-model", help="Vision-capable model for ChemicalOCRAgent")
    parser.add_argument("--chemical-temperature", type=float, default=0.01)
    parser.add_argument("--chemical-max-tokens", type=int, default=1800)
    parser.add_argument("--chemical-timeout", type=float, default=180.0)
    parser.add_argument("--chemical-data-limit", type=int)
    parser.add_argument("--chemical-limit", type=int)
    parser.add_argument("--chemical-max-crops-per-figure", type=int, default=12)
    parser.add_argument("--chemical-no-response-format", action="store_true")


def settings_from_args(args: argparse.Namespace) -> AgentSettings:
    return AgentSettings(
        model=args.model,
        review_model=args.review_model,
        base_url=args.base_url,
        temperature=args.temperature,
        pages_per_window=args.pages_per_window,
        render_pages=not args.no_images,
        max_image_pages_per_window=args.max_image_pages_per_window,
        page_dpi=args.page_dpi,
        review_candidates=not args.no_review,
        review_context_chars=args.review_context_chars,
        max_pages=args.max_pages,
    )


def scraper_config_from_args(args: argparse.Namespace, *, allow_scrape_sqlite: bool) -> ScraperPipelineConfig:
    if args.scrape_sqlite and not allow_scrape_sqlite:
        raise SystemExit("--scrape-sqlite is only supported for the single-PDF extract command.")
    return ScraperPipelineConfig(
        scraper_dir=args.scraper_dir,
        scrape_sqlite=args.scrape_sqlite if allow_scrape_sqlite else None,
        overwrite_scrape=args.overwrite_scrape,
        run_visual=args.run_visual,
        visual_provider=args.visual_provider,
        visual_limit=args.visual_limit,
        run_ocsr=args.run_ocsr,
        ocsr_provider=args.ocsr_provider,
        ocsr_detector_provider=args.ocsr_detector_provider,
        ocsr_limit=args.ocsr_limit,
        ocsr_rerun=args.ocsr_rerun,
        ocsr_batch_size=args.ocsr_batch_size,
        ocsr_device=args.ocsr_device,
        ocsr_min_confidence=args.ocsr_min_confidence,
        run_chemical_agents=args.run_chemical_agents,
        chemical_agent_dir=args.chemical_agent_dir,
        chemical_env_file=args.chemical_env_file,
        chemical_llm_provider=args.chemical_llm_provider,
        chemical_llm_base_url=args.chemical_llm_base_url,
        chemical_data_model=args.chemical_data_model,
        chemical_model=args.chemical_model,
        chemical_temperature=args.chemical_temperature,
        chemical_max_tokens=args.chemical_max_tokens,
        chemical_timeout=args.chemical_timeout,
        chemical_data_limit=args.chemical_data_limit,
        chemical_limit=args.chemical_limit,
        chemical_max_crops_per_figure=args.chemical_max_crops_per_figure,
        chemical_no_response_format=args.chemical_no_response_format,
    )


def scraper_mode_requested(args: argparse.Namespace) -> bool:
    return (
        args.use_scraper
        or bool(args.scrape_sqlite)
        or args.run_visual
        or args.run_ocsr
        or args.run_chemical_agents
    )


def cmd_domains(args: argparse.Namespace) -> None:
    for key, domain in DOMAINS.items():
        print(f"{key}\t{domain.title}\t{domain.hf_dataset}")


def cmd_schema(args: argparse.Namespace) -> None:
    domain = get_domain(args.domain)
    print(json.dumps(structured_output_schema(domain), ensure_ascii=False, indent=2))


def cmd_extract(args: argparse.Namespace) -> None:
    domain = get_domain(args.domain)
    agent = ChemExtractionAgent(domain, settings=settings_from_args(args))
    if scraper_mode_requested(args):
        document = scrape_pdf_to_document(
            args.pdf,
            render_pages=agent.settings.render_pages,
            dpi=agent.settings.page_dpi,
            config=scraper_config_from_args(args, allow_scrape_sqlite=True),
        )
        samples = agent.extract_document(document)
    else:
        samples = agent.extract_pdf(args.pdf)
    output = write_csv(domain, samples, args.out, pdf_name=Path(args.pdf).name)
    print(f"Wrote {len(samples)} rows to {output}")


def cmd_batch(args: argparse.Namespace) -> None:
    domain = get_domain(args.domain)
    use_scraper = scraper_mode_requested(args)
    output = extract_pdf_dir(
        domain,
        args.pdf_dir,
        args.out,
        settings=settings_from_args(args),
        use_scraper=use_scraper,
        scraper_config=scraper_config_from_args(args, allow_scrape_sqlite=False) if use_scraper else None,
    )
    print(f"Wrote batch CSV to {output}")


def cmd_review_csv(args: argparse.Namespace) -> None:
    domain = get_domain(args.domain)
    settings = settings_from_args(args)
    settings.render_pages = False
    use_scraper = scraper_mode_requested(args)
    output = review_prediction_csv(
        domain,
        args.pred,
        args.pdf_dir,
        args.out,
        settings=settings,
        passes=args.passes,
        use_scraper=use_scraper,
        scraper_config=scraper_config_from_args(args, allow_scrape_sqlite=False) if use_scraper else None,
    )
    print(f"Wrote reviewed CSV to {output}")


def cmd_download(args: argparse.Namespace) -> None:
    domain = get_domain(args.domain)
    manifest = download_open_access_pdfs(
        domain,
        args.out_dir,
        limit=args.limit,
        overwrite=args.overwrite,
        mailto=args.mailto,
        include_supplementary=not args.no_supplementary,
    )
    print(manifest["status"].value_counts().to_string())
    print(f"Wrote manifest to {Path(args.out_dir) / 'download_manifest.csv'}")


def cmd_evaluate(args: argparse.Namespace) -> None:
    domain = get_domain(args.domain)
    articles = read_article_ids(args.articles) if args.articles else None
    metrics = evaluate_predictions(
        domain,
        args.pred,
        truth_csv=args.truth_csv,
        article_ids=articles,
    )
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        metrics.to_csv(output)
        print(f"Wrote metrics to {output}")
    print(metrics)
    print(f"Macro-F1: {macro_f1(metrics):.6f}")


def cmd_web(args: argparse.Namespace) -> None:
    import subprocess
    import sys

    app_path = Path(__file__).with_name("web.py")
    raise SystemExit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(app_path)]))


if __name__ == "__main__":
    main()
