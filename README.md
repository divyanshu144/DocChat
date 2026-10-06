# DocChat Agent

A multi-source RAG assistant for asking questions across PDFs, YouTube transcripts and web pages. Sign up, ingest sources, pick a subset, and chat with a LangGraph agent (Planner → Retriever → Synthesizer → Grounding → Critic) that retrieves chunks from Qdrant, writes a cited answer, checks it against the retrieved context, and saves the conversation.

## Quick Setup

### Docker Compose

Prerequisites:

- Docker Desktop
- Node.js 18+ if you want to rebuild the frontend bundle
- A Groq API key, unless you switch `LLM_PROVIDER` to another configured provider

```bash
cp .env.example .env
# Set at minimum:
# GROQ_API_KEY=...
# JWT_SECRET_KEY=<long-random-string>

cd frontend
npm install
npm run build
cd ..

docker compose up --build
```

Open:

- App: `http://localhost:8081`
- API docs: `http://localhost:8081/docs`
- Qdrant dashboard: `http://localhost:6333/dashboard`

### Local Development

Run Postgres and Qdrant locally:

```bash
docker run -p 6333:6333 qdrant/qdrant

docker run \
  -e POSTGRES_USER=docchat \
  -e POSTGRES_PASSWORD=docchat \
  -e POSTGRES_DB=docchat \
  -p 5432:5432 \
  postgres:16-alpine
```

Install and run the backend:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL=postgresql+asyncpg://docchat:docchat@localhost:5432/docchat
export QDRANT_HOST=localhost
export QDRANT_PORT=6333
export GROQ_API_KEY=...
export JWT_SECRET_KEY=...

uvicorn app.main:app --reload
```

Run the frontend in dev mode:

```bash
cd frontend
npm install
npm run dev
```

Build the frontend into the FastAPI static directory:

```bash
cd frontend
npm run build
```

## Features

- **Auth:** JWT access (30 min) and rotating refresh (7 days) tokens, with silent refresh in the client.
- **Multi-source ingestion:** PDFs, YouTube URLs and web pages share one chat; sync and job-based ingest routes.
- **Source scoping:** a sources drawer to select specific documents, plus PDF / YouTube / Web type filters per query.
- **Agentic retrieval:** the planner picks source types, the grounding node removes unsupported claims, the critic can trigger one replan.
- **Citations:** inline `[PDF — name]`, `[YouTube — title]`, `[Web — url]` tags rendered as chips.
- **Folders and history:** folders with drag-and-drop, persisted conversations, token streaming over SSE.
- **Observability:** LangSmith tracing (when configured), request-ID logging, an optional protected Prometheus endpoint.

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI, SSE streaming |
| Agent | LangGraph StateGraph |
| Vector store | Qdrant (`source_chunks`, cosine HNSW) |
| Embeddings | fastembed ONNX, `BAAI/bge-small-en-v1.5`, 384-dim |
| LLM | Groq `openai/gpt-oss-120b` by default; OpenAI, Mistral and self-hosted vLLM (`local`) providers behind `app/services/llm.py` |
| Storage | PostgreSQL + SQLAlchemy 2.0 async |
| Auth | JWT (python-jose) + bcrypt |
| Ingestion | pymupdf, youtube-transcript-api, httpx + trafilatura |
| Frontend | React 18 + Vite + TypeScript |

## Architecture

```text
React + Vite UI --REST + SSE--> FastAPI API
  |-- Auth: JWT + rotating refresh tokens
  |-- Conversations/folders: PostgreSQL
  |-- Ingestion: PDF, YouTube, web -> fastembed -> Qdrant
  `-- Chat: LangGraph agent
        Planner -> Retriever -> Synthesizer -> Grounding -> Critic
                      |             |             |           |
                   Qdrant        LLM API       LLM API     LLM API
```

Layout and the reasoning behind the main decisions: [docs/architecture.md](docs/architecture.md).

## Inference benchmarking

`eval/` holds a harness for measuring serving performance under load (TTFT, decode throughput, p95/p99, queueing, KV-cache use, GPU utilization, cost), plus held-out serving and answer-quality evaluations. Realistic DocChat-shaped prompts, cache-busting by default and a positive control keep the numbers honest.

The most recent live run is [reports/gpu-live-2026-10-06.md](reports/gpu-live-2026-10-06.md): Qwen2.5-7B-Instruct on vLLM 0.30.0, one L40S, one run per configuration, about $1.37 estimated. It covers a concurrency sweep with GPU utilization, SIGSTOP and hard-kill failure-behaviour tests, prefix caching on versus off, and serial versus concurrent. These are single-run, single-GPU numbers, and the report lists what they do not support.

Earlier findings (hosted-API concurrency limits, KV-cache saturation, the harness catching its own measurement mistakes) are in [docs/inference-writeup.md](docs/inference-writeup.md) and [eval/BENCHMARK_RESULTS.md](eval/BENCHMARK_RESULTS.md).

## Verification

```bash
ruff check .                      # clean
pytest -m "not eval" -q           # 629 passed, 8 deselected
cd frontend && npm test -- --run  # frontend tests
python eval/benchmark.py          # critic benchmark; calls the live LLM, opt-in
```

The frontend tests were last recorded at 3 files / 6 tests on 2026-10-01 and were not re-run for this change. Live LLM evals are opt-in because they cost money.

## Documentation

| Doc | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Project structure, RAG/LLM/agent decisions, guardrails, hardening, observability, productionising |
| [docs/api.md](docs/api.md) | API reference, configuration variables, database schema, folders |
| [docs/benchmarking.md](docs/benchmarking.md) | Sustained benchmark, artifacts, comparisons, GPU runbook |
| [docs/serving-observability.md](docs/serving-observability.md) | Serving adapter and timing definitions |
| [docs/inference-writeup.md](docs/inference-writeup.md) | Inference findings and what was never tested |
| [docs/vllm_setup.md](docs/vllm_setup.md) | Self-hosting vLLM |
| [docs/retrieval-quality-evaluation.md](docs/retrieval-quality-evaluation.md) | Retrieval evaluation |
| [docs/grafana-plan.md](docs/grafana-plan.md) | Prometheus and proposed Grafana panels |
