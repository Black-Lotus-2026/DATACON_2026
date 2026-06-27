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
    extract.add_argument("--pdf", required=True, help="Path to article PDF")
    extract.add_argument("--out", required=True, help="Output CSV path")
    extract.set_defaults(func=cmd_extract)

    batch = subparsers.add_parser("batch", help="Extract every PDF in a directory")
    add_agent_args(batch)
    batch.add_argument("--pdf-dir", required=True, help="Directory with PDF files")
    batch.add_argument("--out", required=True, help="Output CSV path")
    batch.set_defaults(func=cmd_batch)

    review_csv = subparsers.add_parser(
        "review-csv",
        help="Refine a prediction CSV with article-level text context",
    )
    add_agent_args(review_csv)
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


def cmd_domains(args: argparse.Namespace) -> None:
    for key, domain in DOMAINS.items():
        print(f"{key}\t{domain.title}\t{domain.hf_dataset}")


def cmd_schema(args: argparse.Namespace) -> None:
    domain = get_domain(args.domain)
    print(json.dumps(structured_output_schema(domain), ensure_ascii=False, indent=2))


def cmd_extract(args: argparse.Namespace) -> None:
    domain = get_domain(args.domain)
    agent = ChemExtractionAgent(domain, settings=settings_from_args(args))
    samples = agent.extract_pdf(args.pdf)
    output = write_csv(domain, samples, args.out, pdf_name=Path(args.pdf).name)
    print(f"Wrote {len(samples)} rows to {output}")


def cmd_batch(args: argparse.Namespace) -> None:
    domain = get_domain(args.domain)
    output = extract_pdf_dir(domain, args.pdf_dir, args.out, settings=settings_from_args(args))
    print(f"Wrote batch CSV to {output}")


def cmd_review_csv(args: argparse.Namespace) -> None:
    domain = get_domain(args.domain)
    settings = settings_from_args(args)
    settings.render_pages = False
    output = review_prediction_csv(
        domain,
        args.pred,
        args.pdf_dir,
        args.out,
        settings=settings,
        passes=args.passes,
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
