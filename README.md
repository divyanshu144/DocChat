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
4. The agent planner chooses source collections, the retriever searches Qdrant, the synthesizer writes a cited answer, the grounding node removes unsupported claims, and the critic may request one replan loop.
5. The backend saves the user and assistant messages to PostgreSQL and streams the final answer to the browser.

## RAG, LLM, And Agent Decisions

### LLM

Default provider is Groq with `llama-3.3-70b-versatile`. I chose it because the app benefits from low-latency chat completions and the model is strong enough for planning, synthesis, grounding, and critique without splitting providers per node.

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

Current caveat from my latest run: the focused route/auth/folder/chat suite passes. The full suite got to 114 passing tests, with 4 failures in `tests/test_critic_eval.py` because those tests make live LLM calls and failed with an event-loop/network cleanup error in my local environment. I would separate live evals from deterministic CI tests.

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
- Add rate limits and abuse protection for auth, ingestion, and chat.
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

The most relevant checks from the latest development pass:

```bash
cd frontend && npm run build && cd ..
# passed

cd frontend && npm run test && cd ..
# 4 passed

python -m pytest tests/test_api_chat.py tests/test_api_conversations.py tests/test_api_folders.py tests/test_api_auth.py
# 16 passed

python -m pytest
# 124 passed, 4 live critic-eval failures in this local environment
```

The full-suite failures were not caused by the chat/folder/auth fixes; they are live LLM evaluator tests that should be split from deterministic CI.
