"""Eval harness tests — assert output SCHEMA only, never literal metric values."""
from evals.run_evals import context_recall, evaluate, faithfulness


def _sample_cases():
    return [
        {"query": "q1", "answer": "show ip ospf neighbor", "contexts": ["show ip ospf neighbor FULL"],
         "reference": "ospf neighbor"},
        {"query": "q2", "answer": "ping 8.8.8.8", "contexts": ["ping diagnostics traceroute"],
         "reference": "ping diagnostics"},
    ]


def test_faithfulness_schema():
    s = faithfulness("show ip ospf", ["show ip ospf neighbor"])
    assert isinstance(s, float)
    assert 0.0 <= s <= 1.0


def test_context_recall_schema():
    s = context_recall(["bgp tcp 179 summary"], "bgp summary")
    assert isinstance(s, float)
    assert 0.0 <= s <= 1.0


def test_evaluate_report_schema():
    report = evaluate(_sample_cases())
    assert set(report) >= {"num_cases", "mean_faithfulness", "mean_context_recall", "results"}
    assert report["num_cases"] == 2
    assert isinstance(report["mean_faithfulness"], float)
    assert isinstance(report["mean_context_recall"], float)
    for r in report["results"]:
        assert set(r) >= {"query", "faithfulness", "context_recall"}
        assert 0.0 <= r["faithfulness"] <= 1.0
        assert 0.0 <= r["context_recall"] <= 1.0
