import pandas as pd

from datacon_agent.batch import rows_for_pdf
from datacon_agent.domains import get_domain
from datacon_agent.metrics import calc_column_metrics


def test_column_metrics_use_multiset_counts() -> None:
    metrics = calc_column_metrics(["a", "a", "b"], ["a", "b", "b"])

    assert metrics["tp"] == 2.0
    assert metrics["fp"] == 1.0
    assert metrics["fn"] == 1.0
    assert round(metrics["precision"], 6) == 0.666667
    assert round(metrics["recall"], 6) == 0.666667
    assert round(metrics["f1"], 6) == 0.666667


def test_rows_for_pdf_keeps_dotted_article_ids() -> None:
    domain = get_domain("nanozymes")
    frame = pd.DataFrame(
        [
            {"pdf": "THNO.19257", "formula": "LaNiO3"},
            {"pdf": "SREP40103", "formula": "Pt"},
        ]
    )

    rows = rows_for_pdf(frame, domain, "THNO.19257")

    assert len(rows) == 1
    assert rows[0]["formula"] == "LaNiO3"
    assert rows[0]["activity"] == "NOT_DETECTED"
