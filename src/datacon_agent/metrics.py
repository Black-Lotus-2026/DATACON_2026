from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable

import pandas as pd

from datacon_agent.domains import NOT_DETECTED, DomainSpec
from datacon_agent.normalize import pdf_identifier


def convert_comma(value: object) -> str:
    try:
        return str(value).replace(",", ".")
    except Exception:
        return str(value)


def canonicalize_smiles(value: object) -> object:
    if value in (None, "", NOT_DETECTED):
        return value
    try:
        from rdkit import Chem
        from rdkit import RDLogger

        RDLogger.DisableLog("rdApp.*")
    except Exception:
        return value

    mol = Chem.MolFromSmiles(str(value))
    if mol is None:
        return value
    return Chem.MolToSmiles(mol)


def prepare_truth(domain: DomainSpec, *, truth_csv: str | Path | None = None) -> pd.DataFrame:
    if truth_csv is None:
        try:
            from datasets import load_dataset
        except Exception as exc:
            raise RuntimeError(
                "Install evaluator dependencies with `uv sync --extra eval` "
                "or pass --truth-csv."
            ) from exc
        dataset = load_dataset(domain.hf_dataset)
        frame = dataset["train"].to_pandas()
    else:
        frame = pd.read_csv(truth_csv)

    frame = frame.copy()
    for column in domain.numeric_fields:
        if column in frame.columns:
            frame[column] = frame[column].apply(convert_comma)
    if domain.key in {"oxazolidinone", "benzimidazole"} and "target_relation" in frame.columns:
        frame["target_relation"] = frame["target_relation"].apply(
            lambda value: "=" if value == "'='" else value
        )
    for column in domain.smiles_fields:
        if column in frame.columns:
            frame[column] = frame[column].apply(canonicalize_smiles)

    if "access" in frame.columns:
        frame = frame.loc[frame["access"] == 1]
    frame = frame.fillna(NOT_DETECTED)
    return frame


def prepare_prediction(domain: DomainSpec, pred_csv: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(pred_csv).copy()
    aliases = {}
    from datacon_agent.domains import ALIASES

    for source, target in ALIASES.get(domain.key, {}).items():
        if source in frame.columns and target not in frame.columns:
            aliases[source] = target
    if aliases:
        frame = frame.rename(columns=aliases)

    for column in domain.columns:
        if column not in frame.columns:
            frame[column] = NOT_DETECTED
    if "pdf" not in frame.columns:
        frame["pdf"] = NOT_DETECTED
    else:
        frame["pdf"] = frame["pdf"].apply(lambda value: pdf_identifier(domain, str(value)))

    for column in domain.numeric_fields:
        if column in frame.columns:
            frame[column] = frame[column].apply(convert_comma)
    for column in domain.smiles_fields:
        if column in frame.columns:
            frame[column] = frame[column].apply(canonicalize_smiles)

    return frame.fillna(NOT_DETECTED)


def calc_column_metrics(true_values: Iterable[object], pred_values: Iterable[object]) -> dict[str, float]:
    true_counter = Counter(str(value) for value in true_values)
    pred_counter = Counter(str(value) for value in pred_values)
    true_positive = float(sum((true_counter & pred_counter).values()))
    false_positive = float(sum((pred_counter - true_counter).values()))
    false_negative = float(sum((true_counter - pred_counter).values()))

    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def calc_metrics(df_true: pd.DataFrame, df_pred: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    metrics = {
        column: calc_column_metrics(
            df_true[column].astype(str).values,
            df_pred[column].astype(str).values,
        )
        for column in columns
    }
    return pd.DataFrame(metrics).T


def evaluate_predictions(
    domain: DomainSpec,
    pred_csv: str | Path,
    *,
    truth_csv: str | Path | None = None,
    article_ids: Iterable[str] | None = None,
) -> pd.DataFrame:
    truth = prepare_truth(domain, truth_csv=truth_csv)
    pred = prepare_prediction(domain, pred_csv)

    truth["pdf"] = truth["pdf"].astype(str).str.lower()
    pred["pdf"] = pred["pdf"].astype(str).str.lower()

    if article_ids is None:
        articles = sorted(truth["pdf"].unique())
    else:
        articles = sorted(str(article).lower() for article in article_ids)
    if not articles:
        return pd.DataFrame(
            {
                "tp": 0.0,
                "fp": 0.0,
                "fn": 0.0,
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
            },
            index=domain.columns,
        )

    aggregate = pd.DataFrame(0.0, index=domain.columns, columns=["tp", "fp", "fn", "precision", "recall", "f1"])
    for article in articles:
        truth_article = truth.loc[truth["pdf"] == article, domain.columns]
        pred_article = pred.loc[pred["pdf"] == article, domain.columns]
        aggregate = aggregate + calc_metrics(truth_article, pred_article, domain.columns)
    return aggregate / len(articles)


def read_article_ids(path: str | Path) -> list[str]:
    text = Path(path).read_text(encoding="utf-8")
    values: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            values.append(stripped)
    return values


def macro_f1(metrics: pd.DataFrame) -> float:
    if metrics.empty:
        return 0.0
    return float(metrics["f1"].mean())
