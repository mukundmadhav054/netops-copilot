"""Mock Ragas-style faithfulness + context-recall harness (no external deps)."""
from __future__ import annotations

import json
import re
import sys


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


def main() -> None:
    report = evaluate(DEFAULT_CASES)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    sys.exit(main())
