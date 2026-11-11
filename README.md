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
- **MCP server:** query, ingest and list documents from any MCP client over stdio (see [MCP server](#mcp-server)).
- **Hybrid retrieval (opt-in):** dense + BM25 fused with reciprocal rank fusion; off by default because it was measurably worse than the default on a 127-question set (see [Hybrid retrieval](#hybrid-retrieval-opt-in)).
- **AWS deployment:** Terraform for ECS Fargate, RDS, Qdrant on EC2 and SQS; deployed once to a real account, verified end to end and torn down (see [AWS deployment](#aws-deployment)).
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

## MCP server

`app/mcp_server.py` exposes the knowledge base to any MCP client (Claude Code, Claude Desktop and others) over stdio, using `FastMCP`. It is a separate entry point from the web API: it does not need the API running, but it does need Qdrant, and the LLM provider keys from `.env`, because `query_documents` runs the full agent pipeline.

| Tool | Arguments | Returns |
|---|---|---|
| `query_documents` | `query` (required), `source_ids` (optional list; omit to search everything) | the answer with inline citations |
| `ingest_document` | `source_type` (`pdf`, `youtube` or `web`), `location` (file path or URL), `name` (optional) | JSON `{source_id, source_type, name}` |
| `list_documents` | none | JSON list of `{source_id, type, name}` |

Add it to a client's MCP config (the `mcpServers` format used by Claude Desktop and by Claude Code's `.mcp.json`), with absolute paths:

```json
{
  "mcpServers": {
    "docchat": {
      "command": "/path/to/docchat/venv/bin/python",
      "args": ["-m", "app.mcp_server"],
      "env": { "PYTHONPATH": "/path/to/docchat", "QDRANT_HOST": "localhost" }
    }
  }
}
```

Or with the Claude Code CLI: `claude mcp add docchat -e PYTHONPATH=/path/to/docchat -e QDRANT_HOST=localhost -- /path/to/docchat/venv/bin/python -m app.mcp_server`.

Notes:

- **Start Qdrant first** (`docker compose up qdrant`). `.env` is read from the project root whatever directory the client starts the server in, but its Qdrant host is the Docker service name, so a server running on the host needs `QDRANT_HOST=localhost` as above. The server logs to stderr; stdout carries the protocol.
- **No authentication or per-user scoping.** The tools do not go through the API's JWT login, folders or conversation history. Whoever can start the server can read, search and add to the whole knowledge base, and `ingest_document` with `pdf` reads any file path the server process can read. Use it on your own machine, not as a shared service.
- **Each query is stateless:** no conversation history is sent or saved. A call can take as long as a chat turn, and counts against your LLM provider's limits.
- **`name`** is stored for PDFs only (as the filename). For YouTube and web sources it is echoed back in the response and not stored.
- Ingestion runs inside the tool call, so a large PDF keeps the call open until it finishes.
- I checked the stdio handshake, the three tool schemas and `list_documents` against a live Qdrant. I did not call `query_documents` or `ingest_document` over stdio while writing this section.

## Hybrid retrieval (opt-in)

By default the retriever takes the dense (cosine) candidates from Qdrant and re-ranks them with a term-overlap score. `RETRIEVAL_MODE=hybrid` instead asks Qdrant for two rankings in one request, dense and BM25 (a sparse `bm25` vector, IDF applied by Qdrant), and fuses them with reciprocal rank fusion (`RETRIEVAL_RRF_K`, default 60). The cosine floor still applies to dense candidates.

**It is off by default on purpose.** On the first 24-question set (17 chunks) it was not better, and that set was too small to settle it, so I built a larger one: 127 questions over 781 chunks from 14 sources, two question styles (exact-term and paraphrase), scored on the production retriever with paired bootstrap intervals. Hybrid was worse: Recall@1 0.583 against 0.693 for the default (95% CI for the difference -0.173 to -0.051) and MRR 0.761 against 0.834. BM25 does beat plain dense search, but the default's `0.75 * cosine + 0.25 * term coverage` blend already captures most of it. The labels are mostly LLM-written and not independently audited, and the corpus is English Wikipedia, so treat this as strong evidence for this retriever on this kind of text, not a general claim. Details, limits and the one untested hybrid variant are in [docs/retrieval-quality-evaluation.md](docs/retrieval-quality-evaluation.md).

- **Falls back by itself** to the default path when the collection has no BM25 field, the BM25 model fails to load, or the query has no indexable terms. The fallback gave identical results on the golden set.
- **Needs a new collection.** Qdrant 1.18 cannot add a sparse field to an existing collection, so `python -m scripts.migrate_to_hybrid_collection` copies the points into a new one (no re-embedding, safe to re-run, never touches the original). Then set `QDRANT_SOURCE_COLLECTION` and `RETRIEVAL_MODE=hybrid`; unsetting them is the rollback. New installs need no migration.
- Ingestion writes BM25 vectors whenever the collection has the field and indexes dense-only into an older one.

## AWS deployment

`infra/terraform` builds the platform: an ALB, the API on ECS Fargate, a worker that scales on queue depth (on Fargate Spot, from zero, in the `demo` profile), RDS PostgreSQL, Qdrant on a small EC2 instance (image mirrored into your own ECR and pulled by digest), SQS and S3 for ingestion, alarms and a dashboard. Start with [docs/aws/deployment.md](docs/aws/deployment.md); [docs/aws/teardown.md](docs/aws/teardown.md) removes it again.

**What has actually been run.** The `dev` environment (the cheap `demo` profile) was applied to a new AWS account on 2026-11-11 and verified end to end: health checks, signup, a web page ingested through SQS and the worker, and a grounded answer streamed back. It was torn down, then applied a second time from merged `master` (127 resources) and verified the same way, which confirmed the fixes below hold (the queued ingest took about 5 minutes, mostly the Spot worker starting from zero). The second stack was torn down too (134 resources) and a check found no NAT gateway, load balancer, instance or database left. The first run found real bugs that offline checks could not:

- Fargate mounts the `/tmp` volume as `root:root`, so the non-root app had no writable temp directory and the worker exited on every start. A one-shot init container now fixes the mode.
- `qdrant-client` switches to HTTPS whenever an API key is set, but Qdrant serves plain HTTP, so every client call failed. The client now passes `https=False`.
- A free-plan AWS account rejects RDS backup retention above one day, so the dev profile sets one day. Images must be built for `linux/amd64` on Apple-silicon Macs.

**Limits.** The demo costs roughly $4 to $5 a day at list prices recalled from memory; I have not seen a real bill. Dev serves plain HTTP and was restricted to one IP. Not exercised: HTTPS with a certificate, the `prod` profile (Multi-AZ, deletion protection), the GitHub deploy workflow, RDS password rotation, task scale-in protection, Spot reclaim during a job, and anything that ran for more than about an hour. The deployed image used the default dense retrieval, not hybrid. See [docs/aws/limitations.md](docs/aws/limitations.md).

## Inference benchmarking

`eval/` holds a harness for measuring serving performance under load (TTFT, decode throughput, p95/p99, queueing, KV-cache use, GPU utilization, cost), plus held-out serving and answer-quality evaluations. Realistic DocChat-shaped prompts, cache-busting by default and a positive control keep the numbers honest.

The most recent live run is [reports/gpu-live-2026-10-06.md](reports/gpu-live-2026-10-06.md): Qwen2.5-7B-Instruct on vLLM 0.30.0, one L40S, one run per configuration, about $1.37 estimated. It covers a concurrency sweep with GPU utilization, SIGSTOP and hard-kill failure-behaviour tests, prefix caching on versus off, and serial versus concurrent. These are single-run, single-GPU numbers, and the report lists what they do not support.

**Quantization comparison** ([reports/heldout-serving-evaluation-2026-10-05.md](reports/heldout-serving-evaluation-2026-10-05.md)). The same Qwen2.5-7B-Instruct served as FP16, AWQ and GPTQ on one L40S under a 40-prompt DocChat-shaped workload (1,920 measured requests, all succeeded). Both quantized formats roughly doubled single-stream throughput (about 85 output tokens/s against 40) and reached about 3.0 requests/s at saturation against 2.1 for FP16, so at a 20-second p95 target the capacity tool estimates 3 GPUs for 5 requests/s with either quantized format against 4 for FP16 (a linear extrapolation, not a multi-GPU measurement). On answer quality, an LLM-assisted and not human-verified review of 120 blinded answers found no difference between formats: on the 16 held-out cases correctness was 88% for FP16 and GPTQ and 75% for AWQ, with wide intervals and almost every case tied ([reports/answer-quality-final-report-v1-v2-2026-10-06.md](reports/answer-quality-final-report-v1-v2-2026-10-06.md)). The corpus is two documents and the second judging pass was not finished, so this is a planning signal, not a quality ranking.

Earlier findings (hosted-API concurrency limits, KV-cache saturation, the harness catching its own measurement mistakes) are in [docs/inference-writeup.md](docs/inference-writeup.md) and [eval/BENCHMARK_RESULTS.md](eval/BENCHMARK_RESULTS.md).

## Fine-tuning and the LiteLLM backend

Two opt-in pieces, both merged to `master`, change nothing by default. `LLM_BACKEND=litellm` routes the LLM calls through LiteLLM with the same fallback and retry rules; measurements and caveats are in [docs/litellm-backend.md](docs/litellm-backend.md). The `finetune/` package builds a grounded-answer training set from open-licence documents, trains a QLoRA adapter and checks it for leakage against the evaluation sets.

The first run is written up in [reports/finetune-vs-base-2026-11-03.md](reports/finetune-vs-base-2026-11-03.md): Qwen2.5-7B-Instruct with and without the adapter, 99 questions about 15 unseen documents. The adapter learns the output format (a well-formed answer for 69 of 84 answerable questions, against 0 of 84 for the base model with this prompt) and short abstentions. A blinded LLM judge (`gpt-5.6-luna`, not human-verified) also rated it better on correctness: 69 of 99 answers correct against 57, and fully supported by the context 55 against 39. On documents unlike the training ones (a PDF and a Wikipedia article) there is no measurable difference. It is one judge, one prompt and one training seed, and the report lists what the numbers do not show.

**Built with Qwen.** The training examples were generated by Qwen2.5-72B-Instruct, which is under the [Qwen LICENSE AGREEMENT](finetune/licenses/Qwen-LICENSE.txt); the student model, Qwen2.5-7B-Instruct, is Apache 2.0. Any copy of the adapter must ship with [finetune/NOTICE](finetune/NOTICE). No Qwen weights are in this repository.

## Verification

```bash
ruff check .                      # clean
pytest -m "not eval" -q           # 1045 passed, 11 skipped, 8 deselected
cd frontend && npm test -- --run  # frontend tests
python eval/benchmark.py          # critic benchmark; calls the live LLM, opt-in
```

Of the 11 skipped tests, 7 need a real PostgreSQL and 4 need the optional LiteLLM package. With `TEST_DATABASE_URL` pointing at a throwaway database whose name contains "test", those 7 tests run as well (see `tests/test_pg_concurrency.py`). No test needs AWS credentials or network access.

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
| [docs/aws/deployment.md](docs/aws/deployment.md) | AWS deployment steps; see also `teardown`, `cost`, `limitations` and `security` in the same folder |
