"""Mock Ragas-style faithfulness + context-recall harness (no external deps)."""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals.battery import INJECTION_CASES, RETRIEVAL_CASES  # noqa: E402
from src.agents.graph import build_default_graph  # noqa: E402
from src.guardrails.filters import BLOCKED_CLI_PATTERNS  # noqa: E402


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def faithfulness(answer: str, contexts: list[str]) -> float:
    """Fraction of answer tokens grounded in retrieved contexts."""
    a = _tokens(answer)
    if not a:
        return 0.0
    c: set[str] = set()
    for ctx in contexts:
        c |= _tokens(ctx)
    if not c:
        return 0.0
    return round(len(a & c) / len(a), 4)


def context_recall(contexts: list[str], reference: str) -> float:
    """Fraction of reference tokens covered by retrieved contexts."""
    r = _tokens(reference)
    if not r:
        return 0.0
    c: set[str] = set()
    for ctx in contexts:
        c |= _tokens(ctx)
    return round(len(r & c) / len(r), 4)


def evaluate(cases: list[dict]) -> dict:
    """Each case: {query, answer, contexts, reference}. Returns per-case + aggregate."""
    results = []
    for case in cases:
        f = faithfulness(case.get("answer", ""), case.get("contexts", []))
        r = context_recall(case.get("contexts", []), case.get("reference", ""))
        results.append({"query": case.get("query", ""), "faithfulness": f, "context_recall": r})
    agg = {
        "num_cases": len(results),
        "mean_faithfulness": round(sum(x["faithfulness"] for x in results) / max(len(results), 1), 4),
        "mean_context_recall": round(sum(x["context_recall"] for x in results) / max(len(results), 1), 4),
        "results": results,
    }
    return agg


DEFAULT_CASES = [
    {
        "query": "OSPF neighbor stuck in EXSTART?",
        "answer": "show ip ospf neighbor verify FULL state check MTU show interfaces status",
        "contexts": ["OSPF neighbor troubleshooting: use show ip ospf neighbor to verify FULL state. Check MTU with show interfaces status."],
        "reference": "OSPF neighbor FULL state MTU interfaces status",
    },
    {
        "query": "Configure GigabitEthernet1 address?",
        "answer": "configure terminal interface GigabitEthernet1 ip address show running-config",
        "contexts": ["IOS-XE interface config: configure terminal interface GigabitEthernet1 ip address. Verify with show running-config."],
        "reference": "configure terminal interface ip address running-config",
    },
]


def score_battery_offline() -> dict:
    """Run the shared battery through the local graph (same seed as the API).

    Returns per-case faithfulness / context_recall plus intent-routing
    accuracy and retrieval hit rate (expected source in top-3). Text-quality
    means cover only cases with an expected source; unsupported refusals
    retrieve nothing by design and are scored on intent only.
    """
    graph = build_default_graph()
    per_case = []
    for case in RETRIEVAL_CASES:
        state = graph.run(case["query"])
        f = faithfulness(state.answer, state.contexts)
        r = context_recall(state.contexts, case["reference"])
        exp_src = case.get("expected_source")
        hit = (exp_src in state.sources) if exp_src else (state.sources == [])
        per_case.append(
            {
                "query": case["query"],
                "expected_intent": case["expected_intent"],
                "intent": state.intent,
                "intent_ok": state.intent == case["expected_intent"],
                "expected_source": exp_src,
                "sources": state.sources,
                "hit": hit,
                "faithfulness": f,
                "context_recall": r,
            }
        )
    sourced = [c for c in per_case if c["expected_source"]]
    leaks = sum(
        count_leaks(graph.run(p).answer) for p in INJECTION_CASES
    )
    return {
        "num_cases": len(per_case),
        "num_sourced": len(sourced),
        "num_injection": len(INJECTION_CASES),
        "intent_accuracy": round(
            sum(1 for c in per_case if c["intent_ok"]) / max(len(per_case), 1), 4
        ),
        "hit_rate": round(sum(1 for c in per_case if c["hit"]) / max(len(per_case), 1), 4),
        "mean_faithfulness": round(
            sum(c["faithfulness"] for c in sourced) / max(len(sourced), 1), 4
        ),
        "mean_context_recall": round(
            sum(c["context_recall"] for c in sourced) / max(len(sourced), 1), 4
        ),
        "injection_leaks_offline": leaks,
        "results": per_case,
    }


def count_leaks(answer: str) -> int:
    """Number of destructive-CLI pattern matches emitted in an answer."""
    return sum(
        1
        for p in BLOCKED_CLI_PATTERNS
        for _ in re.finditer(p, answer, flags=re.IGNORECASE)
    )


def main() -> None:
    report = evaluate(DEFAULT_CASES)
    print(json.dumps(report, indent=2))
    print("--- offline battery ---")
    print(json.dumps(score_battery_offline(), indent=2))


if __name__ == "__main__":
    sys.exit(main())
