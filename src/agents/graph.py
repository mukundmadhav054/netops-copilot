"""Lightweight LangGraph-style conditional execution graph (pure Python).

Nodes: intent -> retrieve -> guardrail -> respond. No langchain/langgraph
dependency required; mirrors their conditional-edge semantics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from src.guardrails.filters import contains_injection, guard_response, sanitize_input
from src.retrieval.hybrid import HybridRetriever

INTENTS = ("troubleshoot", "config", "explain", "unsupported")


def route_intent(query: str) -> str:
    q = query.lower()
    if contains_injection(query):
        return "unsupported"
    if any(w in q for w in ("what is", "explain", "rfc", "define", "how does")):
        return "explain"
    if any(w in q for w in ("ospf", "bgp", "down", "flap", "latency", "packet loss", "troubleshoot", "ping fail", "link")):
        return "troubleshoot"
    if any(w in q for w in ("configure", "config", "ios-xe", "cli", "command", "interface", "route")):
        return "config"
    # default: explain-style informational
    return "explain" if len(q.split()) > 2 else "unsupported"


MOCK_LLM_TEMPLATES = {
    "troubleshoot": "Troubleshooting plan based on retrieved context:\n{context}\nSteps: 1) `show ip ospf neighbor` 2) `ping {target}` 3) `show interfaces status`. Recommendation: {query}",
    "config": "Candidate IOS-XE snippet (read-only, verify before apply):\n{context}\nFor `{query}`, use `show running-config interface` to inspect, then stage changes in `configure terminal`.",
    "explain": "Explanation grounded in retrieved docs:\n{context}\nQuestion: {query}",
    "unsupported": "I can't help with that request. Try asking about OSPF/BGP troubleshooting, IOS-XE show commands, or RFC concepts.",
}


def mock_llm(intent: str, query: str, contexts: list[str], target: str = "8.8.8.8") -> str:
    ctx = "\n---\n".join(contexts) if contexts else "(no context retrieved)"
    tpl = MOCK_LLM_TEMPLATES.get(intent, MOCK_LLM_TEMPLATES["unsupported"])
    return tpl.format(context=ctx, query=query, target=target)


@dataclass
class GraphState:
    query: str
    session_id: str = "default"
    intent: str = ""
    contexts: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    answer: str = ""
    blocked: bool = False
    history: list[dict[str, Any]] = field(default_factory=list)


class ConditionalGraph:
    """Minimal conditional graph with named nodes + router edges."""

    def __init__(self, retriever: HybridRetriever):
        self.retriever = retriever
        self.nodes: dict[str, Callable[[GraphState], GraphState]] = {
            "intent": self._intent,
            "retrieve": self._retrieve,
            "guardrail": self._guardrail,
            "respond": self._respond,
        }

    def _intent(self, s: GraphState) -> GraphState:
        s.query = sanitize_input(s.query)
        s.intent = route_intent(s.query)
        return s

    def _retrieve(self, s: GraphState) -> GraphState:
        if s.intent == "unsupported":
            s.contexts, s.sources = [], []
            return s
        hits = self.retriever.search(s.query, top_k=3)
        s.contexts = [h["text"] for h in hits]
        s.sources = [h["payload"].get("source", h["id"]) for h in hits]
        return s

    def _guardrail(self, s: GraphState) -> GraphState:
        # pre-response gate: injection already sanitized; flag if needed
        if contains_injection(s.query):
            s.intent = "unsupported"
            s.contexts, s.sources = [], []
        return s

    def _respond(self, s: GraphState) -> GraphState:
        raw = mock_llm(s.intent, s.query, s.contexts)
        safe, blocked = guard_response(raw)
        s.answer, s.blocked = safe, blocked
        s.history.append({"q": s.query, "a": s.answer, "intent": s.intent})
        return s

    def run(self, query: str, session_id: str = "default") -> GraphState:
        state = GraphState(query=query, session_id=session_id)
        # conditional edges: unsupported skips retrieval context but still responds
        for node in ("intent", "retrieve", "guardrail", "respond"):
            state = self.nodes[node](state)
        return state


def build_default_graph() -> ConditionalGraph:
    """Seeded retriever with sample networking docs for API/tests."""
    r = HybridRetriever()
    r.add(
        [
            "OSPF neighbor troubleshooting: use `show ip ospf neighbor` to verify FULL state. If stuck in EXSTART, check MTU with `show interfaces status`. RFC 2328 defines OSPF adjacency states.",
            "IOS-XE interface config: `configure terminal`, `interface GigabitEthernet1`, `ip address 10.0.0.1 255.255.255.0`, `no shutdown`. Verify with `show running-config interface GigabitEthernet1`.",
            "BGP basics: eBGP uses TCP 179. Check sessions with `show ip bgp summary`. RFC 4271 describes BGP path selection.",
            "Ping/traceroute diagnostics: `ping 8.8.8.8 source GigabitEthernet1`, `traceroute 8.8.8.8`. Packet loss points to link or MTU issues.",
        ],
        [{"source": "rfc2328-troubleshoot"}, {"source": "iosxe-interface"},
         {"source": "rfc4271-bgp"}, {"source": "diagnostics-ping"}],
    )
    return ConditionalGraph(r)
