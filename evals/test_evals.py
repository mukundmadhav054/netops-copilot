"""Eval harness tests — assert output SCHEMA only, never literal metric values."""
from evals.battery import INJECTION_CASES, RETRIEVAL_CASES
from evals.live_bench import _percentile, is_blocked, summarize
from evals.run_evals import context_recall, count_leaks, evaluate, faithfulness, score_battery_offline
from src.agents.graph import INTENTS


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


def test_battery_composition_schema():
    assert len(RETRIEVAL_CASES) >= 10
    assert len(INJECTION_CASES) >= 15
    intents = {c["expected_intent"] for c in RETRIEVAL_CASES}
    assert {"troubleshoot", "config", "explain", "unsupported"} <= intents
    for c in RETRIEVAL_CASES:
        assert set(c) >= {"query", "expected_intent", "expected_source", "reference"}
        assert c["query"] and c["reference"]
        assert c["expected_intent"] in INTENTS
        assert c["expected_source"] is None or isinstance(c["expected_source"], str)
    for p in INJECTION_CASES:
        assert isinstance(p, str) and p.strip()


def test_offline_battery_report_schema():
    report = score_battery_offline()
    assert set(report) >= {
        "num_cases", "num_sourced", "num_injection", "intent_accuracy",
        "hit_rate", "mean_faithfulness", "mean_context_recall",
        "injection_leaks_offline", "results",
    }
    assert report["num_cases"] == len(RETRIEVAL_CASES)
    assert report["num_injection"] == len(INJECTION_CASES)
    for k in ("intent_accuracy", "hit_rate", "mean_faithfulness", "mean_context_recall"):
        assert isinstance(report[k], float)
        assert 0.0 <= report[k] <= 1.0
    assert isinstance(report["injection_leaks_offline"], int)
    assert report["injection_leaks_offline"] >= 0
    for r in report["results"]:
        assert set(r) >= {"query", "intent", "intent_ok", "sources", "hit",
                          "faithfulness", "context_recall"}
        assert isinstance(r["intent_ok"], bool) and isinstance(r["hit"], bool)


def test_count_leaks_schema():
    assert isinstance(count_leaks("show ip ospf neighbor"), int)
    assert count_leaks("show ip ospf neighbor") == 0
    assert count_leaks("please reload now") >= 1


def test_percentile_schema():
    vals = sorted([5.0, 1.0, 3.0, 9.0, 7.0])
    assert _percentile(vals, 0.50) in vals
    assert _percentile(vals, 0.99) >= _percentile(vals, 0.50)
    assert _percentile([], 0.5) == 0.0


def test_is_blocked_schema():
    assert is_blocked("unsupported", "I can't help with that request.", False) is True
    assert is_blocked("explain", "Run reload now", True) is True
    assert is_blocked("explain", "Explanation grounded in docs.", False) is False


def test_summarize_report_schema():
    rows = [
        {"group": "retrieval", "query": "q", "latency_ms": 4.0, "n_429": 0,
         "expected_intent": "explain", "intent": "explain", "intent_ok": True,
         "expected_source": "s", "sources": ["s"], "hit": True,
         "blocked_flag": False, "faithfulness": 0.5, "context_recall": 0.5},
        {"group": "injection", "query": "p", "latency_ms": 6.0, "n_429": 0,
         "intent": "unsupported", "blocked_flag": False, "blocked": True,
         "leaks": 0, "answer_head": "I can't help"},
    ]
    rep = summarize(rows)
    assert set(rep) >= {"n_total", "latency_ms", "intent_accuracy", "hit_rate",
                        "block_rate", "leaked_total", "mean_faithfulness",
                        "mean_context_recall", "rows"}
    assert rep["n_total"] == 2
    assert rep["leaked_total"] == 0
    lat = rep["latency_ms"]
    assert set(lat) >= {"n", "min", "p50", "p99", "max", "mean"}
    assert lat["min"] <= lat["p50"] <= lat["p99"] <= lat["max"] or lat["n"] == 0
