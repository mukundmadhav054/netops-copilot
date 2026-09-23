# netops-copilot — Agentic RAG & CLI Assistant

FastAPI + lightweight conditional-graph agent (LangGraph-style, pure Python),
hybrid dense (mock embeddings) + BM25 retrieval over an in-memory Qdrant-style
store, guardrails, and a mock Ragas-style eval harness. No API keys required.

## Run

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt
pytest -q
pytest evals/ -q
python evals/run_evals.py
uvicorn src.api.main:app --port 8000
```

Endpoints: `GET /healthz`, `POST /query`, `POST /query/stream` (SSE).

Docker: `docker compose config` to validate; `docker compose up --build` to run
api (:8000) + qdrant (:6333). App uses the in-memory store unless `QDRANT_URL` is set.

## Defense (4 rungs)

- **Explain:** query → intent router → hybrid retrieve (Qdrant-style) → guardrail → mock-LLM respond → streamed tokens.
- **Justify:** Qdrant-style store gives filtered payload indexing + cosine vectors in one place; in-memory fake keeps tests hermetic.
- **Trade-off:** multi-step validation adds latency vs single-prompt calls, in exchange for blocking unauthorized CLI output.
- **Scale & failure:** token-bucket backoff (429 + cached fallback); eval scores are computed by `evals/run_evals.py` — no hardcoded metric claims.
