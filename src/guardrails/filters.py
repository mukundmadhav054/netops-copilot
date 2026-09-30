"""Guardrails: prompt-injection filter, schema validation, CLI authorization."""
from __future__ import annotations

import re

from pydantic import BaseModel, field_validator

# Destructive / privileged IOS-XE commands that must never be emitted
BLOCKED_CLI_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\breload\b",
    r"\bwrite\s+mem(ory)?\b",
    r"\bwrite\s+erase\b",
    r"\berase\s+\S+",
    r"\bformat\s+\S+",
    r"\bshutdown\b.*\b(system|device)\b",
    r"\bdelete\s+flash:",
    r"\bno\s+ip\s+routing\b",
    r"\bdebug\s+all\b",
]

ALLOWED_CLI_PREFIXES = (
    "show ",
    "ping ",
    "traceroute ",
    "configure terminal",
    "interface ",
    "no shutdown",  # interface bring-up is safe; bare/box-level shutdown stays blocked
    "ip route ",
    "router ospf ",
    "copy running-config",
)

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"disregard\s+.*instructions",
    r"you\s+are\s+now\s+",
    r"\bDAN\b",
    r"jailbreak",
    r"system\s*prompt",
    r"reveal\s+.*prompt",
    r"exfiltrate",
    r"send\s+.*password",
]


class QueryRequest(BaseModel):
    query: str
    top_k: int = 3
    session_id: str = "default"

    @field_validator("query")
    @classmethod
    def query_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query must be non-empty")
        if len(v) > 2000:
            raise ValueError("query too long (max 2000 chars)")
        return v

    @field_validator("top_k")
    @classmethod
    def top_k_bounds(cls, v: int) -> int:
        if not 1 <= v <= 10:
            raise ValueError("top_k must be 1..10")
        return v


class AgentResponse(BaseModel):
    answer: str
    intent: str
    sources: list[str] = []
    blocked: bool = False
    model: str = "mock"  # provenance: real model id or "mock"


def contains_injection(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t, re.IGNORECASE) for p in INJECTION_PATTERNS)


def sanitize_input(text: str) -> str:
    """Strip control chars and neutralize suspected injection payloads."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text).strip()
    if contains_injection(cleaned):
        cleaned = "[SANITIZED: suspected prompt injection removed] " + re.sub(
            "|".join(INJECTION_PATTERNS), "[blocked]", cleaned, flags=re.IGNORECASE
        )
    return cleaned[:2000]


def is_cli_allowed(command: str) -> bool:
    c = command.strip().lower()
    if any(re.search(p, c, re.IGNORECASE) for p in BLOCKED_CLI_PATTERNS):
        return False
    return command.strip().lower().startswith(ALLOWED_CLI_PREFIXES) or c.startswith("show")


def filter_cli_commands(commands: list[str]) -> list[str]:
    """Keep only allow-listed, non-blocked CLI commands."""
    return [c for c in commands if is_cli_allowed(c)]


def extract_cli_candidates(text: str) -> list[str]:
    """Naive extractor: lines that look like CLI commands.

    The verb must be followed by whitespace/end-of-line so prose lines that
    merely start with e.g. "Ping/..." (like our own diagnostics doc) are not
    treated as commands.
    """
    out = []
    for line in text.splitlines():
        s = line.strip().strip("`").strip()
        if re.match(r"^(show|ping|traceroute|reload|write|erase|format|delete|shutdown|debug|configure|interface|ip route|router ospf|copy|no|rm)(?=\s|$)", s, re.IGNORECASE):
            out.append(s)
    return out


def guard_response(answer: str) -> tuple[str, bool]:
    """Return (safe_answer, blocked_any). Strips unauthorized CLI commands."""
    candidates = extract_cli_candidates(answer)
    bad = [c for c in candidates if not is_cli_allowed(c)]
    safe = answer
    blocked = False
    for b in bad:
        safe = safe.replace(b, "[BLOCKED: unauthorized command removed]")
        blocked = True
    # Second pass: neutralize blocked destructive patterns anywhere in the
    # text (e.g. echoed back from a user query), so they are never emitted.
    for p in BLOCKED_CLI_PATTERNS:
        new_safe, n = re.subn(p, "[BLOCKED: unauthorized command removed]", safe, flags=re.IGNORECASE)
        if n:
            safe, blocked = new_safe, True
    return safe, blocked
