from __future__ import annotations

from pathlib import Path

import pandas as pd
from tqdm import tqdm

from datacon_agent.agent import AgentSettings, ChemExtractionAgent
from datacon_agent.domains import DomainSpec
from datacon_agent.normalize import samples_to_frame


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
