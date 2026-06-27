from datacon_agent.metrics import calc_column_metrics


def test_column_metrics_use_multiset_counts() -> None:
    metrics = calc_column_metrics(["a", "a", "b"], ["a", "b", "b"])

    assert metrics["tp"] == 2.0
    assert metrics["fp"] == 1.0
    assert metrics["fn"] == 1.0
    assert round(metrics["precision"], 6) == 0.666667
    assert round(metrics["recall"], 6) == 0.666667
    assert round(metrics["f1"], 6) == 0.666667
