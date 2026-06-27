from __future__ import annotations

from pathlib import Path

import pandas as pd
from tqdm import tqdm

from datacon_agent.agent import AgentSettings, ChemExtractionAgent
from datacon_agent.domains import NOT_DETECTED, DomainSpec
from datacon_agent.normalize import finalize_samples, pdf_identifier, samples_to_frame
from datacon_agent.pdf import load_pdf


def extract_pdf_dir(
    domain: DomainSpec,
    pdf_dir: str | Path,
    output_path: str | Path,
    *,
    settings: AgentSettings,
) -> Path:
    directory = Path(pdf_dir)
    pdfs = sorted(path for path in directory.iterdir() if path.suffix.lower() == ".pdf")
    frames: list[pd.DataFrame] = []
    agent = ChemExtractionAgent(domain, settings=settings)

    for pdf_path in tqdm(pdfs, desc=f"Extract {domain.key}"):
        samples = agent.extract_pdf(pdf_path)
        frames.append(samples_to_frame(domain, samples, pdf_name=pdf_path.name))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if frames:
        pd.concat(frames, ignore_index=True).to_csv(output, index=False)
    else:
        pd.DataFrame(columns=[*domain.columns, "pdf"]).to_csv(output, index=False)
    return output


def review_prediction_csv(
    domain: DomainSpec,
    pred_csv: str | Path,
    pdf_dir: str | Path,
    output_path: str | Path,
    *,
    settings: AgentSettings,
    passes: int = 1,
) -> Path:
    directory = Path(pdf_dir)
    pdfs = sorted(path for path in directory.iterdir() if path.suffix.lower() == ".pdf")
    predictions = pd.read_csv(pred_csv, dtype=str).fillna(NOT_DETECTED)
    agent = ChemExtractionAgent(domain, settings=settings)
    pass_count = max(1, passes)

    for pass_index in range(pass_count):
        frames: list[pd.DataFrame] = []
        desc = f"Review {domain.key}" if pass_count == 1 else f"Review {domain.key} pass {pass_index + 1}/{pass_count}"
        for pdf_path in tqdm(pdfs, desc=desc):
            pdf_id = pdf_identifier(domain, pdf_path.name)
            candidates = rows_for_pdf(predictions, domain, pdf_id)
            document = load_pdf(pdf_path, render_pages=False)
            reviewed = agent.review(candidates, document=document)
            rows = finalize_samples(domain, reviewed)
            frames.append(samples_to_frame(domain, rows, pdf_name=pdf_path.name))
        if frames:
            predictions = pd.concat(frames, ignore_index=True)
        else:
            predictions = pd.DataFrame(columns=[*domain.columns, "pdf"])

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(output, index=False)
    return output


def rows_for_pdf(frame: pd.DataFrame, domain: DomainSpec, pdf_id: str) -> list[dict]:
    if "pdf" not in frame.columns:
        subset = frame.iloc[0:0]
    else:
        normalized_pdf = frame["pdf"].map(lambda value: pdf_identifier(domain, str(value)))
        subset = frame.loc[normalized_pdf == pdf_id]
    for column in domain.columns:
        if column not in subset.columns:
            subset = subset.assign(**{column: NOT_DETECTED})
    return subset.loc[:, domain.columns].to_dict(orient="records")
