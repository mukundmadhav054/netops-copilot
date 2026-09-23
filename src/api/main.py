"""Async FastAPI backend: streaming endpoint + /healthz, token-bucket backoff, fallback cache."""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from src.agents.graph import build_default_graph
from src.guardrails.filters import AgentResponse, QueryRequest

app = FastAPI(title="netops-copilot", version="0.1.0")
graph = build_default_graph()

# --- token-bucket rate limiter (in-process) ---
_TOKENS = 20.0
_LAST = time.monotonic()
_RATE = 5.0  # tokens/sec
_MAX = 20.0


def _allow(n: int = 1) -> bool:
    global _TOKENS, _LAST
    now = time.monotonic()
    _TOKENS = min(_MAX, _TOKENS + (now - _LAST) * _RATE)
    _LAST = now
    if _TOKENS >= n:
        _TOKENS -= n
        return True
    return False


# --- fallback cache: last good answer per normalized query ---
CACHE: dict[str, dict] = {}


class Health(BaseModel):
    status: str
    version: str


@app.get("/healthz", response_model=Health)
async def healthz() -> Health:
    return Health(status="ok", version=app.version)


@app.post("/query", response_model=AgentResponse)
async def query(req: QueryRequest) -> AgentResponse:
    if not _allow():
        # backoff: serve cached fallback if present
        key = req.query.strip().lower()
        if key in CACHE:
            c = CACHE[key]
            return AgentResponse(answer=c["answer"] + "\n[cached fallback: rate-limited]", intent=c["intent"], sources=c["sources"])
        raise HTTPException(status_code=429, detail="rate limited, retry later")
    state = await asyncio.to_thread(graph.run, req.query, req.session_id)
    resp = AgentResponse(answer=state.answer, intent=state.intent, sources=state.sources, blocked=state.blocked)
    CACHE[req.query.strip().lower()] = {"answer": state.answer, "intent": state.intent, "sources": state.sources}
    return resp


@app.post("/query/stream")
async def query_stream(req: QueryRequest):
    if not _allow(2):
        raise HTTPException(status_code=429, detail="rate limited, retry later")
    state = await asyncio.to_thread(graph.run, req.query, req.session_id)
    CACHE[req.query.strip().lower()] = {"answer": state.answer, "intent": state.intent, "sources": state.sources}

    async def gen() -> AsyncIterator[str]:
        for tok in state.answer.split():
            yield f"data: {tok}\n\n"
            await asyncio.sleep(0)
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.exception_handler(HTTPException)
async def http_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
