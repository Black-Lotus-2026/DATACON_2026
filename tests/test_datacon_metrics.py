import pandas as pd

from datacon_agent.batch import rows_for_pdf
from datacon_agent.domains import DOMAINS, get_domain
from datacon_agent.metrics import calc_column_metrics, prepare_truth


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


def test_eyedrops_domain_is_registered() -> None:
    domain = get_domain("eyedrops")

    assert "eyedrops" in DOMAINS
    assert domain.hf_dataset == "ai-chem/EyeDrops"
    assert domain.columns == ["smiles", "name", "perm (cm/s)", "logP"]


def test_eyedrops_truth_uses_pmid_as_article_id(tmp_path) -> None:
    truth_path = tmp_path / "eyedrops.csv"
    pd.DataFrame(
        [
            {
                "smiles": "CCO",
                "name": "ethanol",
                "perm (cm/s)": "-5,2",
                "logP": "-0,3",
                "doi": "",
                "PMID": "123456",
                "title": "Corneal permeability test",
                "access": "0",
            }
        ]
    ).to_csv(truth_path, index=False)

    frame = prepare_truth(get_domain("eyedrops"), truth_csv=truth_path)

    assert frame.loc[0, "pdf"] == "123456"
    assert frame.loc[0, "perm (cm/s)"] == "-5.2"
    assert frame.loc[0, "logP"] == "-0.3"
