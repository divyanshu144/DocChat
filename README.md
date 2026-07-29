# DocChat Agent

A multi-source agentic research assistant. Sign up, ingest PDFs, YouTube videos, and web pages into a shared vector store, then ask questions across all of them. A five-node LangGraph agent — Planner → Retriever → Synthesizer → Grounding → Critic — orchestrates retrieval and generates cited answers that stream token-by-token to the browser.

---

## How it works

```
Ingest (PDF / YouTube / Web)
        │
        ▼
  Text extraction
  (pymupdf · youtube-transcript-api · trafilatura)
        │
        ▼
  Chunking + Embedding
  (fastembed · BAAI/bge-small-en-v1.5 · ONNX · 384-dim)
        │
        ▼
  Qdrant  ──  pdf_chunks / youtube_chunks / web_chunks
        │
        │   At query time
        ▼
  ┌─── Planner ────────────────────────────────┐
  │  Selects which source collections to query  │
  └────────────────────┬───────────────────────┘
                       ▼
  ┌─── Retriever ──────────────────────────────┐
  │  Semantic search across selected Qdrant     │
  │  collections; filters by source_id if set   │
  └────────────────────┬───────────────────────┘
                       ▼
  ┌─── Synthesizer ────────────────────────────┐
  │  Groq LLM builds a cited answer from chunks │
  │  Streamed token-by-token via SSE            │
  └────────────────────┬───────────────────────┘
                       ▼
  ┌─── Grounding ──────────────────────────────┐
  │  Verifies claims in the answer are backed   │
  │  by retrieved chunks; adds source tags      │
  └────────────────────┬───────────────────────┘
                       ▼
  ┌─── Critic ─────────────────────────────────┐
  │  Quality gate — triggers replan loop if     │
  │  answer is incomplete or unsupported        │
  └────────────────────────────────────────────┘
```

---

## Tech stack

| Layer | Technology |
|---|---|
| API framework | FastAPI |
| Agent orchestration | LangGraph (StateGraph) |
| Vector store | Qdrant (REST API · cosine HNSW index) |
| Embeddings | fastembed ONNX · `BAAI/bge-small-en-v1.5` · 384-dim |
| LLM | Groq API · `llama-3.3-70b-versatile` |
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
- **Agentic retrieval** — the Planner node selects which collections are relevant before querying; the Grounding node verifies claims; the Critic node can trigger a replan loop if answer quality is too low
- **Citation tags** — answers include inline `[PDF — filename]`, `[YouTube — title]`, `[Web — url]` tags rendered as colour-coded chips
- **Source type filter chips** — toggle PDF / YouTube / Web collections per query without re-ingesting
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
venv/bin/python -m pytest -m "not eval" -q   # 109 passed, 8 deselected
```

The critic benchmark is intentionally separate because it hits the live LLM:

```bash
venv/bin/python eval/benchmark.py
```

---

## Project structure

```
app/
├── agent/
│   ├── graph.py           # Compiled LangGraph StateGraph — entry point: agent_graph.ainvoke()
│   ├── state.py           # AgentState TypedDict (includes source_ids filter field)
│   └── nodes/
│       ├── planner.py     # Source collection selection
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
│   │   ├── pdf.py         # pymupdf → chunks → Qdrant pdf_chunks
│   │   ├── youtube.py     # transcript-api + pytube → Qdrant youtube_chunks
│   │   └── web.py         # httpx + trafilatura → Qdrant web_chunks
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

## Setup

### Docker Compose (recommended)

**Prerequisites:** Docker Desktop, a [Groq API key](https://console.groq.com)

```bash
# 1. Clone the repo
git clone <repo-url>
cd docchat

# 2. Configure environment
cp .env.example .env
# Set GROQ_API_KEY=gsk_... and JWT_SECRET_KEY=<random-string> in .env

# 3. Build the React frontend
cd frontend && npm install && npm run build && cd ..

# 4. Start the full stack (app + Qdrant + PostgreSQL)
docker compose up --build
```

Open `http://localhost:8081` for the UI, or `http://localhost:8081/docs` for API docs.

- Qdrant dashboard: `http://localhost:6333/dashboard`
- PostgreSQL: `localhost:5433` from the host, `postgres:5432` inside Compose (user/pass/db: `docchat`)

### Local dev (without Docker)

**Prerequisites:** Python 3.13, Node.js 18+, Qdrant and PostgreSQL running locally

```bash
# 1. Start Qdrant
docker run -p 6333:6333 qdrant/qdrant

# 2. Start PostgreSQL
docker run -e POSTGRES_USER=docchat -e POSTGRES_PASSWORD=docchat \
           -e POSTGRES_DB=docchat -p 5432:5432 postgres:16-alpine

# 3. Create and activate virtual environment
python -m venv venv
source venv/bin/activate

# 4. Install Python dependencies
pip install -r requirements.txt

# 5. Build the React frontend
cd frontend && npm install && npm run build && cd ..

# 6. Configure environment
cp .env.example .env
# Set: GROQ_API_KEY, JWT_SECRET_KEY
# Set: QDRANT_HOST=localhost, QDRANT_PORT=6333
# Set: DATABASE_URL=postgresql+asyncpg://docchat:docchat@localhost:5432/docchat

# 7. Run the dev server
uvicorn app.main:app --reload
```

Open `http://localhost:8000` — the React SPA is served at `/`.

For frontend hot-reload during development:

```bash
cd frontend && npm run dev   # runs on http://localhost:5173, proxies /api → :8000
```

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

- `sources` — filter which Qdrant collections the agent queries (`pdf`, `youtube`, `web`). Omit to query all three.
- `source_ids` — restrict retrieval to specific ingested documents by their `source_id`. Omit (or pass `[]`) to search across all sources in the selected collections.

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
GET /api/v1/health  →  {"status": "ok", "version": "2.0.0"}
```

---

## Configuration

All settings load from environment variables or a `.env` file.

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `groq` | Chat provider: `groq`, `openai`, or `mistral` |
| `FALLBACK_LLM_PROVIDER` | `openai` | Cross-provider fallback for retryable Groq failures; requires `OPENAI_API_KEY` |
| `GROQ_API_KEY` | *(required for Groq)* | Groq API key |
| `OPENAI_API_KEY` | *(required for OpenAI)* | OpenAI API key |
| `JWT_SECRET_KEY` | *(required)* | Secret for signing JWTs — use a long random string |
| `DATABASE_URL` | `postgresql+asyncpg://docchat:docchat@localhost:5432/docchat` | SQLAlchemy async DSN |
| `QDRANT_HOST` | `localhost` | Qdrant host (use `qdrant` inside Docker Compose) |
| `QDRANT_PORT` | `6333` | Qdrant REST port |
| `CHAT_MODEL` | `llama-3.3-70b-versatile` | Groq model ID |
| `GROQ_FALLBACK_CHAT_MODEL` | *(empty)* | Optional same-provider Groq fallback before cross-provider fallback |
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
