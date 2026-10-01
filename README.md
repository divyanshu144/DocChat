# DocChat Agent

DocChat is a multi-source RAG assistant for asking questions across PDFs, YouTube transcripts, and web pages. Users can sign up, ingest sources, select a subset of those sources, and chat with a LangGraph-powered assistant that retrieves relevant chunks, synthesizes an answer, grounds it against the retrieved context, and saves the conversation.

This README is written as an engineering handoff. It includes what I built, why I made the main decisions, what is production-ready, and what I would harden before running this on a hyperscaler.

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

## Tech stack

| Layer | Technology |
|---|---|
| API framework | FastAPI |
| Agent orchestration | LangGraph (StateGraph) |
| Vector store | Qdrant (REST API · cosine HNSW index) |
| Embeddings | fastembed ONNX · `BAAI/bge-small-en-v1.5` · 384-dim |
| LLM | Groq API · `openai/gpt-oss-120b` (optional OpenAI fallback; Mistral and self-hosted vLLM providers — see [Inference benchmarking](#inference-benchmarking)) |
| Streaming | Server-Sent Events via FastAPI `StreamingResponse` |
| Conversation store | PostgreSQL + SQLAlchemy 2.0 async |
| Auth | JWT (python-jose) + bcrypt · access + refresh tokens |
| PDF extraction | pymupdf |
| YouTube transcripts | youtube-transcript-api · pytube |
| Web scraping | httpx · trafilatura |
| Observability | LangSmith (auto-enabled when `LANGSMITH_API_KEY` is set) |
| Frontend | React 18 + Vite + TypeScript |
| Containerisation | Docker Compose |

---

## Features

- **JWT authentication** — sign up / log in with email + password; access tokens (30 min) + refresh tokens (7 days) with automatic silent refresh
- **Multi-source ingestion** — drag-and-drop PDFs, paste YouTube URLs, or scrape any web page; all sources share a single chat interface
- **Sources drawer** — a slide-in panel from the right side of the screen for ingesting and selecting sources; never compresses the chat area
- **Per-source filtering** — check individual sources in the drawer to restrict retrieval to only those sources; an orange badge on the Sources button shows how many are active
- **Agentic retrieval** — the Planner node selects source types to filter in `source_chunks`; the Grounding node verifies claims; the Critic node can trigger a replan loop if answer quality is too low
- **Citation tags** — answers include inline `[PDF — filename]`, `[YouTube — title]`, `[Web — url]` tags rendered as colour-coded chips
- **Source type filter chips** — toggle PDF / YouTube / Web source types per query without re-ingesting
- **Conversation folders** — create named folders to organise chats; drag-and-drop conversations into folders; open a new chat scoped to a folder with the `+` button on the folder header
- **Session persistence** — conversations survive page refresh; the last active conversation is automatically restored from `localStorage`
- **Token streaming** — answers appear word-by-word; a blinking cursor shows the stream is live
- **LangSmith tracing** — every agent run produces a full trace (nodes, token counts, latencies) when `LANGSMITH_API_KEY` is set

---

## Evaluation posture

This project is built to be judged on more than a happy-path demo:

| Criterion | Evidence in the repo |
|---|---|
| Working document Q&A | End-to-end ingestion, vector search, cited synthesis, source filters, persisted conversations, and SSE streaming. |
| Trust and product UX | Inline citation chips, per-answer citation coverage, active corpus/collection scope in the composer, source drawer, folders, and conversation continuity. |
| Engineering quality | FastAPI/LangGraph module boundaries, typed React components, JWT refresh flow, Docker Compose, Qdrant/PostgreSQL separation, ruff + pytest gates, and benchmark/eval scripts. |
| Observability | LangSmith tracing when configured, health endpoint, structured eval output, and source/citation state visible in the UI. |

Current local verification baseline:

```bash
venv/bin/python -m ruff check .
venv/bin/python -m pytest -m "not eval" -q   # 368 passed, 8 deselected
```

The critic benchmark is intentionally separate because it hits the live LLM:

```bash
venv/bin/python eval/benchmark.py
```

---

## Inference benchmarking

DocChat also carries a self-hosted-inference benchmarking harness, built to measure
serving performance under load rather than just answer quality — `eval/inference_benchmark.py`
sweeps TTFT, decode throughput, and cost across a concurrency range for any configured
provider (`groq`, `openai`, `mistral`, or a self-hosted vLLM server via the `local`
provider above), using the same `chat_stream` seam the app itself calls.

```bash
python eval/inference_benchmark.py --providers local \
  --prompts-file data/bench_prompts.jsonl --concurrency 1,4,16,64,128 \
  --max-tokens 1400 --gpu-cost-per-hr 1.09
```

What makes the numbers trustworthy, not just fast-looking:

- **Realistic prompts** — `eval/capture_bench_prompts.py` captures DocChat's actual
  planner→retriever→synthesizer request shape (3.7k-6.8k input tokens, real retrieval
  context), not a toy 20-90 token query.
- **Cache-busting by default** — every request gets a unique token prepended
  client-side, so a concurrency sweep can't silently measure its own KV-cache hits
  instead of real inference.
- **Live vLLM `/metrics` instrumentation** — prefix-cache hit rate, KV cache usage,
  queue depth, and preemption count are scraped during each cell, so a busting claim is
  backed by the server's own counters, not just code review.
- **A positive control before any sweep is trusted** — `eval/positive_control.py` sends
  one prompt twice with busting off (expect a real cache hit) and twice with busting on
  (expect ~0%) and refuses to proceed if that split isn't observed.

**Headline finding:** at realistic prompt sizes, hosted-API concurrency limits bind
before raw latency does. OpenAI returned `429` on the majority of requests at
concurrency 4+ on this account's tier. Self-hosting removes that account-tier ceiling,
but it does not remove queueing under load: a corrected, cache-busted sweep showed the
GPU's own KV cache climbing to 99.4% full at high concurrency, with real client-side
timeouts once it saturated. The honest framing is that self-hosting trades someone
else's account-tier quota for a ceiling you can see, size, and control yourself, not
"no ceiling at all."

A second finding came from the harness catching its own measurement mistakes before
trusting its own output: a wrong workload (40-100x smaller than DocChat's real request
shape), a wall-time bug that inflated one throughput number by over 6x, and a
cache-contaminated latency measurement were each found and fixed, with direct evidence,
inside this same body of work. See `docs/inference-writeup.md` for the short version of
that story and the corrected findings, or `eval/BENCHMARK_RESULTS.md` for the full
sweep-by-sweep data behind it.

---

## Project structure

```
app/
├── agent/
│   ├── graph.py           # Compiled LangGraph StateGraph — entry point: agent_graph.ainvoke()
│   ├── state.py           # AgentState TypedDict (includes source_ids filter field)
│   └── nodes/
│       ├── planner.py     # Source type selection
│       ├── retriever.py   # Qdrant semantic search with optional source_id filter
│       ├── synthesizer.py # Groq answer generation (streaming)
│       ├── grounding.py   # Claim verification against retrieved chunks
│       └── critic.py      # Quality gate + replan trigger
├── api/
│   ├── auth.py            # POST /auth/signup, /auth/login, /auth/refresh, /auth/logout, GET /auth/me
│   ├── chat.py            # POST /chat — runs agent, saves history, streams SSE
│   ├── conversations.py   # GET/PATCH /conversations — list, detail, move to folder
│   ├── folders.py         # CRUD /folders
│   ├── health.py
│   └── ingest.py          # POST /ingest/{pdf,youtube,web} · GET/DELETE /sources
├── core/
│   ├── qdrant.py          # QdrantClient singleton + get_qdrant_collection()
│   ├── config.py          # Pydantic Settings — all env vars
│   ├── database.py        # Async SQLAlchemy engine, startup migration, get_db
│   ├── deps.py            # FastAPI dependencies: get_current_user
│   └── security.py        # JWT encode/decode, bcrypt hash/verify
├── models/
│   ├── conversation.py    # Folder + Conversation + Message SQLAlchemy models
│   ├── user.py            # User SQLAlchemy model
│   └── refresh_token.py   # RefreshToken SQLAlchemy model (hashed, expiry)
├── services/
│   ├── embedder.py        # fastembed wrapper (shared by ingestion + retrieval)
│   ├── ingestion/
│   │   ├── pdf.py         # pymupdf → independent embeddings → source_chunks
│   │   ├── youtube.py     # transcript-api + httpx → source_chunks
│   │   └── web.py         # httpx + trafilatura → source_chunks
│   └── llm.py             # AsyncGroq client — chat_complete() and chat_stream()
├── static/                # Built React SPA (generated by `npm run build`)
│   ├── index.html
│   └── assets/
└── main.py                # FastAPI app factory, middleware, router registration

frontend/                  # React 18 + Vite + TypeScript source
├── src/
│   ├── api.ts             # Typed fetch wrapper; ssePost for SSE streaming
│   ├── types.ts           # TypeScript interfaces (Source, TokenResponse, …)
│   ├── App.tsx            # Root: auth gate, lifted state, layout, drawer state
│   ├── styles.css         # Design system — dark theme, CSS custom properties
│   └── components/
│       ├── AuthScreen.tsx   # Login / signup form
│       ├── Sidebar.tsx      # Folders, conversations, drag-and-drop, context menu
│       ├── SourcesDrawer.tsx# Slide-in right drawer: ingest + source selection
│       └── ChatPanel.tsx    # SSE streaming chat with filter chips + Sources button
├── vite.config.ts         # base: '/static/', outDir: '../app/static'
└── package.json
```

---

## Architecture Overview

```text
React + Vite UI
  |
  | REST + Server-Sent Events
  v
FastAPI API
  |
  |-- Auth: JWT access tokens + rotating refresh tokens
  |-- Conversations/folders: PostgreSQL via SQLAlchemy async
  |-- Ingestion: PDF, YouTube, web extraction
  |-- Chat: streams agent progress and final answer
  v
LangGraph agent
  Planner -> Retriever -> Synthesizer -> Grounding -> Critic
                    |             |            |
                    v             v            v
                 Qdrant        LLM API      LLM API
                    ^
                    |
         fastembed embeddings during ingestion
```

Key directories:

- `frontend/src`: React UI, auth-aware API client, SSE chat panel, source drawer, folders.
- `app/api`: FastAPI routers for auth, ingestion, chat, conversations, folders, health.
- `app/agent`: LangGraph state machine and nodes.
- `app/services/ingestion`: PDF, YouTube, and web extraction pipelines.
- `app/services/embedder.py`: `fastembed` wrapper.
- `app/services/llm.py`: provider abstraction for Groq, Mistral, and OpenAI-style chat completions.
- `app/core`: config, database, Qdrant, auth dependencies, JWT/password utilities.
- `tests`: API, model, ingestion, agent, eval, and service tests.

The runtime flow is:

1. The user ingests a PDF, YouTube URL, or web URL.
2. The ingestion service extracts text, chunks it, embeds it with `BAAI/bge-small-en-v1.5`, and writes vectors plus metadata to Qdrant.
3. The user asks a question. The frontend posts to `/api/v1/chat` and reads an SSE stream.
4. The agent planner chooses source type filters, the retriever searches Qdrant, the synthesizer writes a cited answer, the grounding node removes unsupported claims, and the critic may request one replan loop.
5. The backend saves the user and assistant messages to PostgreSQL and streams the final answer to the browser.

## RAG, LLM, And Agent Decisions

### LLM

Default provider is Groq with `openai/gpt-oss-120b`. I chose it because the app benefits from low-latency chat completions and the model is strong enough for planning, synthesis, grounding, and critique without splitting providers per node.

The LLM code is isolated in `app/services/llm.py`. Agent nodes call only `chat_complete` or `chat_stream`, not vendor SDKs. That made it straightforward to add provider branches for Groq, Mistral, and OpenAI, and it keeps future model evaluation from becoming a repo-wide refactor.

I also added retry/fallback behavior for retryable Groq failures. If configured, OpenAI can be used as a fallback provider. In production I would make this policy explicit per endpoint and expose fallback events in metrics.

### Embedding Model

The embedding model is `BAAI/bge-small-en-v1.5` through `fastembed`, producing 384-dimensional vectors. I chose it because it is fast, local, cheap to run, and good enough for a broad document-Q&A baseline. The local ONNX path also avoids an external embedding API dependency during ingestion.

The tradeoff is quality ceiling. For a production knowledge assistant, I would benchmark this against a larger embedding model and possibly a reranker before increasing complexity.

### Vector Database

Qdrant now uses a normalized chunk collection for new ingests:

- `source_chunks`

Every point carries `source_id`, `source_type`, chunk text, and source-specific metadata. Retrieval filters by payload instead of choosing a different collection per source type. That means a future source type can reuse the same storage, listing, deletion, retrieval, and citation-label path without adding another Qdrant collection.

The app still tolerates legacy `pdf_chunks`, `youtube_chunks`, and `web_chunks` during source listing/deletion so existing local data can be cleaned up.

### Orchestration Framework

The agent uses LangGraph:

```text
Planner -> Retriever -> Synthesizer -> Grounding -> Critic
                                      ^             |
                                      |-------------|
                                      max one replan
```

I chose LangGraph over a simple function chain because the critic/replan path is stateful and easier to reason about as a graph. I kept the graph small on purpose. More nodes would look sophisticated but would make quality harder to debug without clear eval wins.

### Prompt And Context Management

The planner sees the user query, the last 10 conversation messages, and critic feedback if a previous answer was poor. It returns strict JSON with selected source types and an optional rewritten query.

The retriever embeds the query, searches `source_chunks`, applies source-type/source-id metadata filters, deduplicates chunks, and then applies a lightweight local reranker that combines vector score with lexical overlap. The frontend can pass selected source IDs, which take precedence over source-type filters so future source types are still retrievable when selected directly.

The synthesizer receives reranked chunks and recent conversation history. Its prompt explicitly says to answer from context only, explain missing information, ignore instructions embedded in retrieved chunks, and put citations in a final `Sources:` section.

The current context strategy is still intentionally simple:

- Fixed recent history limit: 10 messages.
- Configurable prompt context budget: `CONTEXT_MAX_CHARS`.
- Reranked retrieval before context packing.
- No query decomposition beyond planner rewrite.
- Character-budget context packing rather than tokenizer-exact packing.

That is acceptable for the scope of this project, but it is the first place I would invest more time.

### Guardrails

Implemented guardrails:

- Authenticated API routes with JWT access tokens and rotating refresh tokens.
- Client-side refresh coalescing so concurrent 401s do not reuse a revoked refresh token.
- Source selection filters, so users can restrict retrieval to trusted documents.
- Grounding node that removes claims not supported by retrieved chunks.
- Prompt-injection guard text in synthesis and grounding prompts, with hostile-document regression tests.
- Critic node that can trigger one replan if the answer is incomplete or vague.
- Citation markers generated from chunk metadata.
- Password hashing with bcrypt and refresh-token hashes stored server-side.

Guardrails I would add before production:

- Rate limiting by user and IP.
- Upload size, MIME, and content scanning policies.
- Tenant isolation tests for every data path.
- Prompt-injection defenses that treat retrieved text as untrusted data.
- Moderation or policy checks if the deployed use case requires them.
- Stronger refresh token session management: device metadata, revocation lists, and audit logs.

### Quality

The repository has tests across API routes, ingestion, models, agent nodes, LLM provider seams, and benchmark/eval utilities. I also added targeted regression coverage for the streamed-conversation commit race.

Important validation commands:

```bash
cd frontend && npm run build && cd ..
cd frontend && npm run test && cd ..
python -m pytest tests/test_api_chat.py tests/test_api_conversations.py tests/test_api_folders.py tests/test_api_auth.py
python -m pytest
```

The fixed-case RAG harness is explicit rather than part of normal CI because it can call live LLM providers:

```bash
python eval/rag_harness.py \
  --providers groq openai \
  --embedding-models BAAI/bge-small-en-v1.5 \
  --retrieval-top-k 2 3 \
  --prompt-profiles baseline strict_cited
```

Current offline suite: 368 passed, 8 live critic evals deselected. Live LLM evals remain opt-in because they incur API cost. The historical event-loop client-cache issue was fixed; it is not a current failing-test baseline.

### Hardening controls

`UPLOAD_MAX_BYTES` defaults to 50 MiB; direct and job-based PDF uploads return
413 beyond it. `INGEST_BATCH_SIZE` defaults to 64. All source types use independent
CPU chunk embeddings. Same-source re-ingestion deletes the previous points before
batched upsert, preventing orphan chunks when a source shrinks. Delete/upsert is
not transactional; retry a failed indexing job.

PDF progress is awaited, and startup marks interrupted queued/running jobs as error.
This deployment uses one app worker. Use a durable queue and shared source locks
before running independent workers.

Login, signup and chat have per-IP sliding-window limits of 10, 5 and 30 requests
per 60 seconds; configure `LOGIN_RATE_LIMIT`, `SIGNUP_RATE_LIMIT`, `CHAT_RATE_LIMIT`
and `RATE_LIMIT_WINDOW_SECONDS`. Rejections return 429 with `Retry-After`. The limiter
is bounded and per-process; forwarded headers are not trusted by it. A reverse proxy
must supply the correct trusted client address before enabling per-client limits.

Refresh-token rotation atomically consumes a token. Reusing a stored revoked token
revokes every refresh token for that user, including successors and other sessions;
other users are unaffected. Existing access tokens still expire normally.

The planner can rewrite retrieval queries, but synthesis and critique use the original
question. Empty retrieval produces an insufficient-context answer without an LLM call.

The read-only [retrieval evaluation](reports/retrieval-evaluation.md) compares dense,
current lexical and CPU cross-encoder ranking on 24 real-corpus questions. Production
ranking is unchanged. Grounding-verdict and critic-context redesigns are spec-only.

### Observability

Current observability:

- FastAPI request logging middleware with request IDs, paths, statuses, and durations.
- `/api/v1/health` endpoint.
- LangSmith tracing when `LANGSMITH_API_KEY` is configured.
- Agent status events streamed to the UI during each run.
- Evaluation scripts and JSON reports under `eval/`, `scripts/`, and `reports/`.

Production observability should add:

- Structured JSON logs.
- OpenTelemetry traces across API, agent nodes, LLM calls, Qdrant, and Postgres.
- Metrics for latency, token usage, retrieval hit counts, grounding failures, replan rate, refresh failures, ingestion failures, and SSE disconnects.
- Dashboards and alerts by route, provider, and tenant.
- Stored eval results over time, so model/prompt changes are measurable.

## Key Technical Decisions

- I used FastAPI because the app is API-first, async I/O-heavy, and benefits from simple typed request/response models.
- I used React + Vite because the frontend needs a real interactive app, not a static demo page, and Vite keeps iteration fast.
- I used PostgreSQL for users, folders, conversations, messages, and refresh-token state because these are relational and transactional.
- I used Qdrant only for vector search, not as the application database, because conversations and auth need normal relational guarantees.
- I committed a new conversation before exposing `X-Conversation-Id` from the streaming chat endpoint. That makes the API contract honest: if the client receives an ID, follow-up routes can find it.
- I coalesced client refresh attempts behind one promise. The backend rotates refresh tokens, so the frontend must not let parallel expired requests race each other with the same token.
- I kept provider-specific LLM code behind one module. Model/provider experiments should not leak into every agent node.
- I kept citation formatting metadata-driven. The answer prompt should not have to infer where a chunk came from.
- I accepted simple retrieval first. Reranking, hybrid search, and query decomposition are useful only after there is a baseline to compare against.

## Productionising On AWS, GCP, Azure, Or Cloudflare

The current Docker Compose setup is good for local development. To productionise it on a hyperscaler, I would make the following changes.

### Runtime And Deployment

- Build immutable backend and frontend images in CI.
- Run the FastAPI app on a managed container platform:
  - AWS: ECS Fargate or EKS.
  - GCP: Cloud Run or GKE.
  - Azure: Container Apps or AKS.
  - Cloudflare: Workers for edge/API-adjacent pieces, but the Python/LangGraph app is better suited to containers unless rewritten.
- Put the app behind a managed load balancer with TLS, HTTP/2, request timeouts compatible with SSE, and WAF rules.
- Use blue/green or canary deployments with health checks and automatic rollback.
- Serve static frontend assets from object storage/CDN:
  - AWS S3 + CloudFront.
  - GCP Cloud Storage + Cloud CDN.
  - Azure Blob Storage + Azure CDN.
  - Cloudflare Pages/R2.

### Data Stores

- Move Postgres to a managed service:
  - AWS RDS/Aurora Postgres.
  - GCP Cloud SQL or AlloyDB.
  - Azure Database for PostgreSQL.
- Move Qdrant to Qdrant Cloud or run it as a managed StatefulSet with persistent disks, snapshots, and tested restore procedures.
- Add migrations with Alembic instead of startup-time schema changes.
- Add backups, point-in-time recovery, retention policies, and restore drills.

### Secrets And Configuration

- Store secrets in AWS Secrets Manager, GCP Secret Manager, Azure Key Vault, or Cloudflare Secrets.
- Rotate LLM API keys and JWT secrets through deployment automation.
- Remove insecure defaults such as the development JWT secret and Compose database credentials.
- Separate dev, staging, and production config.

### Security

- Enforce HTTPS, secure cookies if tokens are moved out of localStorage, CORS allowlists, CSP headers, and upload restrictions.
- Add shared, multi-worker rate limits and ingestion abuse protection. Basic per-IP auth/chat limits already run in-process.
- Add per-user or per-tenant authorization checks around sources as well as conversations.
- Add audit logs for login, refresh, logout, ingest, delete, and admin operations.
- Scan uploaded files and isolate text extraction if handling untrusted documents at scale.

### Scalability

- Move ingestion to a background queue so large PDFs or slow web fetches do not tie up API workers.
  - AWS SQS + ECS workers.
  - GCP Pub/Sub + Cloud Run jobs/workers.
  - Azure Service Bus + Container Apps jobs.
- Store original uploads in object storage, not local disk.
- Add backpressure for LLM calls and Qdrant writes.
- Use autoscaling based on request concurrency, CPU, queue depth, and provider latency.
- Consider separate worker pools for chat, ingestion, and eval jobs.

### Reliability

- Add idempotency keys for ingestion and chat creation paths.
- Add retries with jitter for transient Qdrant, Postgres, and LLM failures.
- Add circuit breakers for LLM providers.
- Persist partial ingestion state so failed jobs can resume or be retried safely.
- Test SSE behavior through the actual load balancer, because proxy buffering/timeouts can break streaming.

### LLM Inference Serving

The points above are generic web-tier scaling. The LLM call itself scales differently,
and the [inference benchmarking](#inference-benchmarking) work in this repo measured
exactly where it breaks — these points are grounded in that data, not generic advice:

- **The real ceiling is KV-cache capacity, not CPU or request count.** A concurrency
  sweep against a self-hosted vLLM instance (L40S 48GB) showed KV cache usage climbing
  from 1.6% at concurrency 1 to 99.4% at concurrency 128, with `num_requests_waiting`
  peaking at 96 — the GPU was queueing, not idling. Autoscale a self-hosted GPU pool on
  vLLM's own `/metrics` (`num_requests_waiting`, `kv_cache_usage_perc`), not on CPU
  utilization or raw request count, which stay low right up until the cache is full.
- **Admission control has to act before the client gives up.** At 99.4% KV usage, 13 of
  128 requests in that sweep failed with client-side `ReadTimeout`/`PoolTimeout` — the
  server queued them past the client's patience rather than rejecting them early. A
  production router should shed load (fast 429/503 with retry-after) once KV usage
  crosses a threshold (e.g. 90%), instead of letting vLLM's own queue silently grow.
- **Context length is a capacity lever, not just a quality one.** KV footprint scales
  with tokens-in-flight; DocChat's real retrieval-augmented prompts run 3.7k-6.8k input
  tokens. Trimming retrieved context (fewer/shorter chunks) directly raises how many
  concurrent requests fit in a fixed KV budget — a tuning knob most request-count-based
  capacity planning misses entirely.
- **Continuous batching trades per-request speed for aggregate throughput — size SLAs
  around that, not raw tok/s.** The same sweep measured per-request decode speed
  dropping from 48.7 tok/s (c=1) to 4.3 tok/s (c=128) while aggregate throughput kept
  climbing — expected behavior, but a dashboard that only shows aggregate tok/s hides
  the p50/p95 latency users actually feel under load.
- **A single GPU's ceiling is a hard wall, not a soft limit** — once KV cache is full,
  only more GPU capacity (another replica behind a router, a bigger GPU, or
  quantization to shrink the per-request memory footprint) fixes it; waiting doesn't.
  AWQ/GPTQ quantization is a planned follow-up specifically to measure that tradeoff
  against the FP16/bf16 numbers already collected.
- **Benchmark dashboards need to separate real throughput from cache-inflated
  throughput.** Production traffic will organically hit vLLM's prefix cache on shared
  system prompts — real signal, not a bug — but a load-testing or capacity-planning
  harness that reuses prompts across measurement runs will silently measure its own
  cache instead of the GPU's real capacity, exactly the self-caught bug documented in
  `eval/BENCHMARK_RESULTS.md`. Any inference dashboard should track prefix-cache hit
  rate alongside throughput so the two numbers are never read as the same thing.

## Engineering Standards Followed

- Kept clear module boundaries: API routers, core infrastructure, services, agent nodes, and frontend components are separate.
- Used typed Pydantic models and TypeScript interfaces where they improve correctness.
- Used async database and HTTP clients for I/O-heavy paths.
- Added focused regression tests for bugs instead of relying only on manual verification.
- Kept secrets in environment variables, not source files.
- Used password hashing and server-side refresh-token rotation rather than long-lived bearer tokens.
- Preferred small, explicit prompts and graph nodes over a large opaque agent prompt.
- Built the React app as a real application with authentication, persistent conversations, source selection, and streaming states.

Standards skipped or incomplete:

- No Alembic migration chain yet.
- No deterministic CI separation between unit tests and live LLM evals.
- No full OpenTelemetry implementation.
- No formal load tests.
- No infrastructure-as-code for cloud deployment.
- No comprehensive threat model.

## How I Used AI Tools

I used AI tools as an implementation and review accelerator, not as a substitute for understanding the system.

Practically, that meant:

- Asking the assistant to inspect unfamiliar areas of the codebase and summarize likely fault lines.
- Using it to generate first-pass patches for narrow bugs, then validating those patches against the actual code and tests.
- Using code review output to identify race conditions I might not have caught from happy-path testing, specifically refresh-token rotation and streamed conversation folder assignment.
- Asking for test ideas around concurrency and transaction timing.
- Manually checking diffs, running builds/tests, and deciding which fixes belonged in the backend contract versus the frontend workflow.

For this README, the content reflects my engineering interpretation of the code and the tradeoffs. I did not want a generic "AI project" README; the useful part is being honest about the current design, what is production-ready, and where the shortcuts are.

## What I Would Do Differently With More Time

- Replace startup schema mutation with Alembic migrations and a real migration history.
- Move background ingestion from FastAPI background tasks to a durable worker queue for multi-instance deployments.
- Add OpenTelemetry and provider-cost tracking from the start.
- Replace the lightweight lexical reranker with a measured reranking model if evals show it improves quality.
- Replace character-budget packing with tokenizer-aware packing per target model.
- Revisit token storage. LocalStorage was pragmatic for this scope; for production I would strongly consider httpOnly secure cookies plus CSRF protection.
- Make live LLM evals opt-in and keep normal CI deterministic.

## Current Verification Snapshot

Verified on 2026-10-01:

```bash
venv/bin/ruff check .
# All checks passed!

venv/bin/python -m pytest -m "not eval" -q
# 368 passed, 8 deselected

cd frontend && npm test -- --run
# 3 files, 6 tests passed
```

The existing frontend build was produced during the SSE fix; this hardening pass
changed no frontend code or generated bundle. Paid API evals were not rerun.

---

## API reference

All endpoints (except `/api/v1/health`, `/api/v1/auth/signup`, `/api/v1/auth/login`, `/api/v1/auth/refresh`) require a Bearer token in the `Authorization` header.

### Auth

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/auth/signup` | Create account and return `access_token` + `refresh_token` |
| `POST` | `/api/v1/auth/login` | Log in; returns `access_token` + `refresh_token` |
| `POST` | `/api/v1/auth/refresh` | Exchange refresh token for new access token |
| `POST` | `/api/v1/auth/logout` | Revoke refresh token |
| `GET` | `/api/v1/auth/me` | Current user info |

**Login example:**

```bash
curl -X POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "secret"}'
# → {"access_token": "eyJ...", "refresh_token": "eyJ...", "token_type": "bearer"}
```

### Ingest

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/ingest/pdf` | Upload a PDF (`multipart/form-data`, field `file`). |
| `POST` | `/api/v1/ingest/youtube` | Ingest a YouTube video (`{"url": "..."}`). |
| `POST` | `/api/v1/ingest/web` | Scrape a web page (`{"url": "..."}`). |
| `GET` | `/api/v1/sources` | List all ingested sources. |
| `DELETE` | `/api/v1/sources/{source_id}` | Delete a source and its chunks from Qdrant. |

There's also an async, job-based path (`POST /api/v1/ingest/{pdf,youtube,web}/jobs` +
`GET /api/v1/ingest/jobs/{job_id}`) for persisted ingestion jobs — added alongside the
synchronous routes above; not yet documented here in detail.

**PDF example:**

```bash
curl -X POST http://localhost:8080/api/v1/ingest/pdf \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@paper.pdf"
```

### Chat

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/chat` | Send a query; returns an SSE stream. Pass `conversation_id` to continue a conversation; omit to start a new one. |

**Request body:**

```json
{
  "query": "What are the key findings?",
  "conversation_id": "optional-uuid",
  "sources": ["pdf", "youtube"],
  "source_ids": ["abc-123", "def-456"]
}
```

- `sources` — filter source types in `source_chunks` (`pdf`, `youtube`, `web`). Omit to search all source types.
- `source_ids` — restrict retrieval to specific ingested documents by their `source_id`. Omit (or pass `[]`) to search across all sources of the selected types.

**Response:** SSE stream — one token per `data:` line, `[DONE]` at end, `[ERROR]` on failure. The response header `X-Conversation-Id` carries the conversation UUID for subsequent requests.

```
data: The

data:  key

data:  findings are...

data: [DONE]
```

### Conversations

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/conversations` | List all conversations (id, title, folder_id, created_at). |
| `GET` | `/api/v1/conversations/{id}` | Get a conversation with full message history. |
| `PATCH` | `/api/v1/conversations/{id}` | Move to a folder (`{"folder_id": "uuid"}`) or unassign (`{"folder_id": null}`). |

### Folders

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/folders` | Create a folder (`{"name": "My Project"}`). |
| `GET` | `/api/v1/folders` | List all folders with conversation counts. |
| `PATCH` | `/api/v1/folders/{id}` | Rename a folder (`{"name": "New Name"}`). |
| `DELETE` | `/api/v1/folders/{id}` | Delete a folder; its conversations become uncategorised. |

### Health

```
GET /api/v1/health
# 200 when both probes succeed; 503 otherwise
# {"status":"ok","version":"2.0.0","timestamp":"...",
#  "dependencies":{"database":"ok","qdrant":"ok"}}
```

---

## Configuration

All settings load from environment variables or a `.env` file.

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `groq` | Chat provider: `groq`, `openai`, `mistral`, or `local` (self-hosted, e.g. vLLM) |
| `FALLBACK_LLM_PROVIDER` | `openai` | Cross-provider fallback for retryable Groq failures; requires `OPENAI_API_KEY` |
| `GROQ_API_KEY` | *(required for Groq)* | Groq API key |
| `OPENAI_API_KEY` | *(required for OpenAI)* | OpenAI API key |
| `LOCAL_BASE_URL` | *(empty)* | Base URL of a self-hosted OpenAI-compatible server (e.g. a vLLM pod); required for `LLM_PROVIDER=local` |
| `LOCAL_CHAT_MODEL` | *(empty)* | Model name as served by the local endpoint |
| `LOCAL_API_KEY` | *(empty)* | Bearer token for the local endpoint, if it requires one |
| `JWT_SECRET_KEY` | *(required)* | Secret for signing JWTs — use a long random string |
| `DATABASE_URL` | `postgresql+asyncpg://docchat:docchat@localhost:5432/docchat` | SQLAlchemy async DSN |
| `QDRANT_HOST` | `localhost` | Qdrant host (use `qdrant` inside Docker Compose) |
| `QDRANT_PORT` | `6333` | Qdrant REST port |
| `CHAT_MODEL` | `openai/gpt-oss-120b` | Groq model ID |
| `GROQ_FALLBACK_CHAT_MODEL` | *(empty)* | Optional same-provider Groq fallback before cross-provider fallback |
| `OPENAI_REASONING_EFFORT` | blank | Optional reasoning setting; blank preserves model default |
| `OPENAI_CHAT_MODEL` | `gpt-5.6-luna` | OpenAI model ID |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | fastembed model name |
| `EMBEDDING_DIM` | `384` | Vector dimension (must match the embedding model) |
| `RETRIEVAL_MIN_SCORE` | `0.3` | Minimum cosine similarity for retrieved chunks |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| `LANGSMITH_API_KEY` | `None` | Enables LangSmith tracing when set |
| `LANGSMITH_PROJECT` | `docchat-agent` | LangSmith project name |
| `DEBUG` | `false` | Enable SQLAlchemy query logging |

---

## Database schema

```
users  ──< refresh_tokens
users  ──< conversations  ──< messages
folders  ──< conversations
```

Schema columns are added automatically at startup via idempotent migrations (using `information_schema.columns` on PostgreSQL). No manual schema changes are needed when upgrading.

---

## Folder & conversation organisation

- **New Folder** — click the button in the sidebar, type a name, press Enter
- **New chat in folder** — hover over a folder name; click the `+` button that appears; the next message you send creates a conversation automatically assigned to that folder
- **Move by drag-and-drop** — drag any conversation item onto a folder header; the folder highlights with a dashed border while hovering; drop to move
- **Move via menu** — hover over a conversation, click `⋯`, select a target folder or "Uncategorized"
- **Delete folder** — `DELETE /api/v1/folders/{id}`; conversations are uncategorised, not deleted
