# DocChat

A production-quality RAG (Retrieval-Augmented Generation) API built with FastAPI. Upload a PDF, DOCX, or TXT file and chat with it in real time — responses stream token-by-token directly to the browser.

---

## How it works

```
Upload document
      │
      ▼
  Text extraction (pypdf / python-docx)
      │
      ▼
  Chunking (500 char, 50 char overlap)
      │
      ▼
  Embedding (fastembed · BAAI/bge-small-en-v1.5 · ONNX)
      │
      ▼
  Stored in SQLite (text + float32 bytes)
      │
      │   At query time
      ▼
  BM25 ranking  +  Cosine similarity ranking
            \         /
             RRF fusion (k=60)
                  │
                  ▼
         Top-k chunks → Groq LLM (llama-3.3-70b-versatile)
                  │
                  ▼
         SSE stream → browser
```

---

## Tech stack

| Layer | Technology |
|---|---|
| API framework | FastAPI 0.104 |
| Database | SQLite + aiosqlite (async), SQLAlchemy 2.0 ORM |
| Embeddings | fastembed (ONNX runtime, no PyTorch) · `BAAI/bge-small-en-v1.5` · 384-dim |
| Sparse retrieval | rank-bm25 (BM25Okapi) with module-level cache |
| Dense retrieval | Cosine similarity over stored float32 embeddings (numpy) |
| Rank fusion | Reciprocal Rank Fusion (RRF, k=60) |
| LLM | Groq API · `llama-3.3-70b-versatile` |
| Streaming | Server-Sent Events via FastAPI `StreamingResponse` |
| Background jobs | FastAPI `BackgroundTasks` (default) or ARQ + Redis (optional) |
| Frontend | Vanilla JS + CSS (no framework) |

---

## Features

- **Hybrid retrieval** — BM25 sparse search and dense semantic search fused with RRF for better recall than either method alone
- **Token streaming** — LLM responses stream directly to the browser via SSE; no waiting for the full reply
- **Background ingestion** — upload returns immediately; the browser polls until the document is ready
- **Per-document BM25 cache** — index is built once per document and reused across all queries; invalidated automatically on re-ingestion
- **WAL mode** — SQLite runs in Write-Ahead Logging mode so reads never block writes
- **Optional Redis queue** — set `REDIS_URL` and run the ARQ worker to move ingestion off the web server entirely
- **Automatic schema migration** — startup adds the `embedding` column and `document_id` index to existing databases without losing data

---

## Project structure

```
app/
├── api/
│   ├── conversations.py   # chat endpoints (sync + SSE stream)
│   ├── documents.py       # upload, list, get
│   └── health.py
├── core/
│   ├── config.py          # pydantic-settings (env / .env)
│   └── database.py        # engine, WAL pragma, migration, get_db
├── models/
│   ├── chunk.py           # Chunk(text, embedding BLOB, document_id)
│   ├── conversation.py
│   ├── document.py        # DocumentStatus: pending → processing → ready | error
│   └── message.py
├── services/
│   ├── chat.py            # Groq client, generate_reply, generate_reply_stream
│   ├── ingestion.py       # extract → chunk → embed → persist
│   ├── retrieval.py       # BM25 cache, cosine sim, RRF
│   └── storage.py         # aiofiles save/delete
├── static/
│   ├── app.js             # upload polling + SSE chat rendering
│   ├── index.html
│   └── styles.css
├── workers/
│   └── tasks.py           # ARQ ingest_document_task + WorkerSettings
└── main.py                # app factory, middleware, router registration
```

---

## Setup

**Prerequisites:** Python 3.13, a [Groq API key](https://console.groq.com)

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd docchat

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create a .env file
echo "GROQ_API_KEY=gsk_..." > .env

# 5. Run the dev server
uvicorn app.main:app --reload
```

Open `http://localhost:8000` for the UI, or `http://localhost:8000/docs` for the interactive API docs.

### Optional: ARQ worker (Redis-backed background ingestion)

```bash
# In a second terminal (REDIS_URL must be set in .env)
arq app.workers.tasks.WorkerSettings
```

When `REDIS_URL` is configured, document ingestion is queued to Redis and processed by the worker instead of the web process.

---

## API reference

### Documents

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/documents` | Upload a document (PDF, DOCX, TXT). Returns immediately with `status: pending`. |
| `GET` | `/api/v1/documents` | List all documents, newest first. |
| `GET` | `/api/v1/documents/{id}` | Get a single document — poll this until `status: ready`. |

**Upload example:**

```bash
curl -X POST http://localhost:8000/api/v1/documents \
  -F "file=@report.pdf;type=application/pdf"
```

```json
{
  "id": "96cf2491-d952-4666-a4cc-6c5fb08162e7",
  "filename": "report.pdf",
  "content_type": "application/pdf",
  "status": "pending",
  "chunk_count": 0,
  "error_message": null,
  "created_at": "2026-03-03T10:38:24"
}
```

### Conversations

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/conversations` | Create a conversation tied to a ready document. |
| `POST` | `/api/v1/conversations/{id}/messages` | Send a message, receive a complete reply. |
| `POST` | `/api/v1/conversations/{id}/messages/stream` | Send a message, receive a token-by-token SSE stream. |
| `GET` | `/api/v1/conversations/{id}` | Fetch a conversation with its full message history. |

**Streaming chat example:**

```bash
curl -N -X POST http://localhost:8000/api/v1/conversations/{id}/messages/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the key findings?"}'
```

```
data: The

data:  key

data:  findings are...

data: [DONE]
```

SSE events: one token per `data:` line, `[DONE]` signals end of stream, `[ERROR]` signals LLM failure.

### Health

```bash
GET /api/v1/health   →   {"status": "ok"}
```

---

## Configuration

All settings load from environment variables or a `.env` file.

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | *(required)* | Groq API key |
| `DATABASE_URL` | `sqlite+aiosqlite:///./docchat.db` | SQLAlchemy async DB URL |
| `UPLOAD_DIR` | `./uploads` | Directory for raw file uploads |
| `MAX_UPLOAD_BYTES` | `10485760` | Maximum upload size (10 MB) |
| `CHAT_MODEL` | `llama-3.3-70b-versatile` | Groq model ID |
| `CHAT_HISTORY_LIMIT` | `10` | Messages kept in LLM context window |
| `RETRIEVAL_TOP_K` | `3` | Chunks returned per query |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | fastembed model name |
| `EMBEDDING_DIM` | `384` | Embedding vector dimension |
| `REDIS_URL` | `None` | Redis DSN — enables ARQ background worker |
| `DEBUG` | `true` | SQLAlchemy query logging |

---

## Document lifecycle

```
pending → processing → ready
                    ↘ error
```

- **pending** — record created, ingestion queued
- **processing** — text is being extracted, chunked, and embedded
- **ready** — chunks stored with embeddings; available for chat
- **error** — ingestion failed; `error_message` has details

Raw upload files are deleted from disk once ingestion finishes (success or error).

---

## Database schema

```
documents  ──< chunks        (document_id FK, indexed)
           ──< conversations ──< messages
```

`chunks.embedding` stores raw `float32` bytes (`numpy.ndarray.tobytes()` / `numpy.frombuffer()`). New columns and indexes are added automatically at startup via the migration function — no manual schema changes needed when upgrading.
