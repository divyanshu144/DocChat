# DocChat Agent

A multi-source agentic research assistant. Ingest PDFs, YouTube videos, and web pages into a shared vector store, then ask questions across all of them. A four-node LangGraph agent — Planner → Retriever → Synthesizer → Critic — orchestrates retrieval and generates cited answers that stream token-by-token to the browser.

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
  (fastembed · BAAI/bge-small-en-v1.5 · ONNX)
        │
        ▼
  ChromaDB  ──  pdf_chunks / youtube_chunks / web_chunks
        │
        │   At query time
        ▼
  ┌─── Planner ────────────────────────────────┐
  │  Selects which source collections to query  │
  └────────────────────┬───────────────────────┘
                       ▼
  ┌─── Retriever ──────────────────────────────┐
  │  Semantic search across selected ChromaDB   │
  │  collections; top-k chunks returned         │
  └────────────────────┬───────────────────────┘
                       ▼
  ┌─── Synthesizer ────────────────────────────┐
  │  Groq LLM builds a cited answer from chunks │
  │  Streamed token-by-token via SSE            │
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
| Vector store | ChromaDB (HTTP client) |
| Embeddings | fastembed ONNX · `BAAI/bge-small-en-v1.5` · 384-dim |
| LLM | Groq API · `llama-3.3-70b-versatile` |
| Streaming | Server-Sent Events via FastAPI `StreamingResponse` |
| Conversation store | SQLite + SQLAlchemy 2.0 async (WAL mode) |
| PDF extraction | pymupdf |
| YouTube transcripts | youtube-transcript-api · pytube |
| Web scraping | httpx · trafilatura |
| Observability | LangSmith (auto-enabled when `LANGSMITH_API_KEY` is set) |
| Frontend | Vanilla JS SPA — no framework |
| Containerisation | Docker Compose |

---

## Features

- **Multi-source ingestion** — drag-and-drop PDFs, paste YouTube URLs, or scrape any web page; all sources share a single chat interface
- **Agentic retrieval** — the Planner node selects which source collections are relevant before querying; the Critic node can trigger a replan loop if the answer quality is too low
- **Citation tags** — answers include inline `[PDF — filename]`, `[YouTube — title]`, `[Web — url]` tags rendered as colour-coded chips
- **Source filter chips** — toggle PDF / YouTube / Web sources per query without re-ingesting
- **Conversation folders** — create named folders to organise chats; drag-and-drop conversations into folders; open a new chat scoped to a folder with the `+` button on the folder header
- **Session persistence** — conversations survive page refresh; the last active conversation is automatically restored from `localStorage`
- **Token streaming** — answers appear word-by-word; a blinking cursor shows the stream is live
- **LangSmith tracing** — every agent run produces a full trace (nodes, token counts, latencies) when `LANGSMITH_API_KEY` is set
- **WAL mode** — SQLite Write-Ahead Logging so reads never block writes
- **Auto migration** — new schema columns are added at startup without manual changes

---

## Project structure

```
app/
├── agent/
│   ├── graph.py           # Compiled LangGraph StateGraph — entry point: agent_graph.ainvoke()
│   ├── state.py           # AgentState TypedDict
│   └── nodes/
│       ├── planner.py     # Source selection
│       ├── retriever.py   # ChromaDB semantic search
│       ├── synthesizer.py # Groq answer generation (streaming)
│       └── critic.py      # Quality gate + replan trigger
├── api/
│   ├── chat.py            # POST /chat — runs agent, saves history, streams SSE
│   ├── conversations.py   # GET/PATCH /conversations — list, detail, move to folder
│   ├── folders.py         # CRUD /folders
│   ├── health.py
│   └── ingest.py          # POST /ingest/{pdf,youtube,web} · GET/DELETE /sources
├── core/
│   ├── chroma.py          # ChromaDB HttpClient singleton + get_collection()
│   ├── config.py          # Pydantic Settings — all env vars
│   └── database.py        # Async SQLAlchemy engine, WAL pragma, startup migration
├── models/
│   └── conversation.py    # Folder + Conversation + Message SQLAlchemy models
├── services/
│   ├── embedder.py        # fastembed wrapper (shared by ingestion + retrieval)
│   ├── ingestion/
│   │   ├── pdf.py         # pymupdf → chunks → ChromaDB pdf_chunks
│   │   ├── youtube.py     # transcript-api + pytube → ChromaDB youtube_chunks
│   │   └── web.py         # httpx + trafilatura → ChromaDB web_chunks
│   └── llm.py             # AsyncGroq client — chat_complete() and chat_stream()
├── static/
│   ├── app.js             # SPA — sidebar, folders, drag-and-drop, streaming chat
│   ├── index.html
│   └── styles.css
└── main.py                # FastAPI app factory, middleware, router registration
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
# Set GROQ_API_KEY=gsk_... in .env

# 3. Start ChromaDB + app
docker-compose up --build
```

Open `http://localhost:8080` for the UI, or `http://localhost:8080/docs` for API docs.

ChromaDB is exposed at `http://localhost:8001` for inspection.

### Local dev (without Docker)

**Prerequisites:** Python 3.13, ChromaDB running locally

```bash
# 1. Start ChromaDB
pip install chromadb
chroma run --host localhost --port 8001 --path ./chroma_data

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env   # set GROQ_API_KEY, CHROMA_HOST=localhost, CHROMA_PORT=8001

# 5. Run the dev server
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

---

## API reference

### Ingest

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/ingest/pdf` | Upload a PDF (`multipart/form-data`, field `file`). |
| `POST` | `/api/v1/ingest/youtube` | Ingest a YouTube video (`{"url": "..."}`). |
| `POST` | `/api/v1/ingest/web` | Scrape a web page (`{"url": "..."}`). |
| `GET` | `/api/v1/sources` | List all ingested sources. |
| `DELETE` | `/api/v1/sources/{source_id}` | Delete a source and its chunks from ChromaDB. |

**PDF example:**

```bash
curl -X POST http://localhost:8080/api/v1/ingest/pdf \
  -F "file=@paper.pdf"
```

**YouTube example:**

```bash
curl -X POST http://localhost:8080/api/v1/ingest/youtube \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
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
  "sources": ["pdf", "youtube"]
}
```

The `sources` array filters which ChromaDB collections the agent queries. Omit to query all three.

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
| `GROQ_API_KEY` | *(required)* | Groq API key |
| `CHROMA_HOST` | `localhost` | ChromaDB host (use `chromadb` inside Docker Compose) |
| `CHROMA_PORT` | `8001` | ChromaDB port |
| `DATABASE_URL` | `sqlite+aiosqlite:///./docchat.db` | SQLAlchemy async DSN |
| `CHAT_MODEL` | `llama-3.3-70b-versatile` | Groq model ID |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | fastembed model name |
| `RETRIEVAL_TOP_K` | `5` | Chunks returned per ChromaDB collection |
| `LANGSMITH_API_KEY` | `None` | Enables LangSmith tracing when set |
| `LANGSMITH_PROJECT` | `docchat` | LangSmith project name |
| `DEBUG` | `false` | Enable SQLAlchemy query logging |

---

## Database schema

```
folders  ──< conversations  ──< messages
```

`folders` and the `folder_id` foreign key on `conversations` are added automatically at startup via an idempotent migration (`PRAGMA table_info` + `ALTER TABLE ADD COLUMN`). No manual schema changes are needed when upgrading.

---

## Folder & conversation organisation

- **New Folder** — click the button in the sidebar, type a name, press Enter
- **New chat in folder** — hover over a folder name; click the `+` button that appears; the next message you send creates a conversation automatically assigned to that folder
- **Move by drag-and-drop** — drag any conversation item onto a folder header; the folder highlights with a dashed border while hovering; drop to move
- **Move via menu** — hover over a conversation, click `⋯`, select a target folder or "Uncategorized"
- **Delete folder** — `DELETE /api/v1/folders/{id}`; conversations are uncategorised, not deleted
