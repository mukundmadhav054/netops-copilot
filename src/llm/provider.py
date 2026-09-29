"""Gemini provider with mock fallback.

No `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) -> everything runs on the
deterministic mock path (embeddings + templates), so tests and local runs
work offline. Any API failure (quota, network, bad key) also degrades to
mock with a warning instead of raising.
"""
from __future__ import annotations

import logging
import os
from typing import Callable

log = logging.getLogger(__name__)

GEN_MODEL = "gemini-3.5-flash-lite"
EMBED_MODEL = "gemini-embedding-001"


def get_api_key() -> str:
    return os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")


def is_configured() -> bool:
    return bool(get_api_key())


def model_name() -> str:
    """Provenance label for responses/health: real model or 'mock'."""
    return GEN_MODEL if is_configured() else "mock"


def _client():  # lazy import: google-genai is optional at import time
    # Singleton: the SDK shares transport state, so per-call clients can
    # end up closed by garbage collection. Create once, reuse, never close.
    global _CLIENT
    if _CLIENT is None:
        from google import genai

        _CLIENT = genai.Client(api_key=get_api_key())
    return _CLIENT


_CLIENT = None


def _grounded_prompt(intent: str, query: str, contexts: list[str]) -> str:
    ctx = "\n---\n".join(contexts) if contexts else "(no context retrieved)"
    return (
        "You are NetOps-Copilot, a network operations assistant. Answer ONLY "
        "from the retrieved context below. If the context lacks the answer, "
        "say so briefly. Include relevant Cisco IOS-XE `show` commands when "
        "they appear in context. NEVER emit destructive or privileged "
        "commands (reload, write erase/mem, erase, format, delete flash:, "
        "rm -rf, shutdown, debug all, no ip routing).\n"
        f"Request type: {intent}\nQuestion: {query}\nContext:\n{ctx}"
    )


def generate_answer(
    intent: str,
    query: str,
    contexts: list[str],
    fallback: Callable[[], str],
) -> tuple[str, str]:
    """Return (answer, model). Falls back to mock on any failure."""
    if not is_configured():
        return fallback(), "mock"
    try:
        resp = _client().models.generate_content(
            model=GEN_MODEL, contents=_grounded_prompt(intent, query, contexts)
        )
        text = (resp.text or "").strip()
        if not text:
            raise ValueError("empty model response")
        return text, GEN_MODEL
    except Exception as exc:  # quota/network/key errors -> mock, never 500
        log.warning("gemini generate failed, using mock fallback: %s", exc)
        return fallback(), "mock"


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Real embeddings, or None (caller keeps mock). Never raises."""
    if not is_configured() or not texts:
        return None
    try:
        resp = _client().models.embed_content(model=EMBED_MODEL, contents=texts)
        return [list(e.values) for e in resp.embeddings]
    except Exception as exc:
        log.warning("gemini embed failed, using mock fallback: %s", exc)
        return None
