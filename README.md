# DocChat

A production-quality RAG (Retrieval-Augmented Generation) application built with FastAPI. Upload a PDF, DOCX, or TXT file and chat with it in real time — responses stream token-by-token directly to the browser via a single-page application.

---

## How it works

```
Upload document
      │
      ▼
  MIME validation + filename sanitisation
      │
      ▼
  Text extraction  (pymupdf / pytesseract OCR / python-docx)
      │  page number + section heading captured per chunk
      ▼
  Sentence-aware chunking  (langchain RecursiveCharacterTextSplitter)
      │
      ▼
  Embedding  (fastembed · BAAI/bge-small-en-v1.5 · ONNX · float16 storage)
      │
      ▼
  Stored in SQLite / PostgreSQL
      │
      │   At query time
      ▼
  Optional HyDE  →  embed hypothetical answer instead of raw question
      │
      ▼
  BM25 ranking  +  Cosine similarity ranking
        \               /
         RRF fusion (k=60)
              │
              ▼
       FlashRank cross-encoder re-rank  (ms-marco-MiniLM-L-12-v2)
              │
              ▼
       Top-k chunks  →  Groq LLM  (llama-3.3-70b-versatile)
              │
              ▼
       SSE stream  →  browser
```

---

## Tech stack

| Layer | Technology |
|---|---|
| API framework | FastAPI |
| Database | SQLite + aiosqlite (default) or PostgreSQL + asyncpg |
| ORM | SQLAlchemy 2.0 async |
| Embeddings | fastembed ONNX · `BAAI/bge-small-en-v1.5` · 384-dim · float16 storage |
| Sparse retrieval | rank-bm25 (BM25Okapi) with NLTK stemming |
| Dense retrieval | Cosine similarity over pre-loaded float32 embedding matrix |
| Rank fusion | Reciprocal Rank Fusion (RRF, k=60) |
| Re-ranking | FlashRank cross-encoder (`ms-marco-MiniLM-L-12-v2` ONNX) |
| LLM | Groq API · `llama-3.3-70b-versatile` |
| Streaming | Server-Sent Events via FastAPI `StreamingResponse` |
| Background jobs | FastAPI `BackgroundTasks` (default) or ARQ + Redis |
| File storage | Local disk (default) or AWS S3 (aioboto3) |
| Cache L1 | In-process LRU (cachetools, maxsize=50) |
| Cache L2 | Redis (optional) — shared across instances, TTL 1 h |
| Semantic cache | Redis cosine-threshold cache per document (optional) |
| Observability | Prometheus metrics at `GET /metrics` |
| Auth | API key header (`X-API-Key`) — optional, no-op in dev |
| Rate limiting | slowapi · 20 req/min on LLM endpoints |
| Frontend | Vanilla JS SPA — hash router, no framework |

---

## Features

- **Single-page application** — hash-based client-side router with three views (Documents, Conversations, Chat); smooth fade transitions; responsive mobile layout
- **Hybrid retrieval** — BM25 sparse + dense semantic search fused via RRF; beats either method alone on recall
- **Cross-encoder re-ranking** — FlashRank ONNX model narrows top-k results to the most relevant before sending to the LLM
- **Token streaming** — LLM responses stream token-by-token to the browser via SSE; no waiting for the full reply
- **HyDE** — optionally embeds a hypothetical answer to improve semantic search on vague queries (`HYDE_ENABLED=true`)
- **Page & section metadata** — chunks carry their PDF page number and section heading, prefixed onto context sent to the LLM
- **Two-layer retrieval cache** — L1 LRU keeps hot documents in-process; L2 Redis shares the cache across instances
- **Semantic cache** — near-duplicate questions are served from Redis without hitting the LLM (`SEMANTIC_CACHE_ENABLED=true`)
- **History summarisation** — when a conversation grows long, older messages are summarised by the LLM and compressed into a system prefix
- **Background ingestion** — upload returns immediately; browser polls until the document is ready; moves to ARQ when `REDIS_URL` is set
- **S3 storage** — set `S3_BUCKET` to store uploads in AWS S3; falls back to local disk automatically
- **PostgreSQL support** — set `DATABASE_URL` to a `postgresql+asyncpg://` DSN for multi-instance deployments; connection pool tunable via env vars
- **MIME validation** — python-magic verifies the actual file content, not just the extension
- **Prometheus metrics** — ingestion, retrieval, re-rank, and LLM latency histograms; cache hit counters
- **WAL mode** — SQLite Write-Ahead Logging so reads never block writes
- **Auto migration** — new columns and indexes are added at startup without manual schema changes

---

## Project structure

```
app/
├── api/
│   ├── conversations.py   # create conv, send message (sync + SSE), rate-limited
│   ├── documents.py       # upload (MIME check, size limit), list, get
│   └── health.py
├── core/
│   ├── config.py          # pydantic-settings — all env vars, use_s3 property
│   ├── database.py        # engine (SQLite WAL / PostgreSQL pool), migration, get_db
│   ├── limiter.py         # shared slowapi Limiter singleton
│   ├── metrics.py         # Prometheus counters and histograms
│   └── security.py        # require_api_key dependency (no-op when API_KEY unset)
├── models/
│   ├── chunk.py           # Chunk(text, embedding BLOB, page_number, section_heading)
│   ├── conversation.py
│   ├── document.py        # DocumentStatus: pending → processing → ready | error
│   └── message.py         # MessageRole, is_complete flag
├── services/
│   ├── chat.py            # Groq client, generate_reply, stream, HyDE, summarise
│   ├── ingestion.py       # extract → chunk → embed → persist (S3-aware)
│   ├── reranker.py        # FlashRank cross-encoder wrapper
│   ├── retrieval.py       # two-layer cache, BM25+cosine, RRF, embed_query
│   ├── semantic_cache.py  # Redis cosine-threshold cache, TTL, invalidation
│   └── storage.py         # local + S3 dual backend, download_for_processing ctx mgr
├── static/
│   ├── app.js             # SPA router, upload modal, streaming chat
│   ├── index.html
│   └── styles.css
├── workers/
│   └── tasks.py           # ARQ ingest_document_task + WorkerSettings
└── main.py                # app factory, middleware, slowapi, /metrics
```

---

## Setup

**Prerequisites:** Python 3.13, a [Groq API key](https://console.groq.com)

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd docchat

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env       # then set GROQ_API_KEY=gsk_...

# 5. Run the dev server
uvicorn app.main:app --reload
```

Open `http://localhost:8000` for the UI, or `http://localhost:8000/docs` for interactive API docs.

### Optional: ARQ background worker

```bash
# Requires REDIS_URL in .env
arq app.workers.tasks.WorkerSettings
```

When `REDIS_URL` is set, document ingestion is queued to Redis and processed by this worker instead of the web process.

---

## API reference

### Documents

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/documents` | Upload a document (PDF, DOCX, TXT). Returns immediately with `status: pending`. |
| `GET` | `/api/v1/documents` | List all documents, newest first. |
| `GET` | `/api/v1/documents/{id}` | Get a single document — poll until `status: ready`. |

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
| `GET` | `/api/v1/conversations` | List all conversations with document name and message count. |
| `POST` | `/api/v1/conversations` | Create a conversation tied to a ready document. |
| `GET` | `/api/v1/conversations/{id}` | Fetch a conversation with full message history. |
| `POST` | `/api/v1/conversations/{id}/messages` | Send a message, receive a complete reply. |
| `POST` | `/api/v1/conversations/{id}/messages/stream` | Send a message, receive a token-by-token SSE stream. |

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

### Health & Metrics

```
GET /api/v1/health   →  {"status": "ok"}
GET /metrics         →  Prometheus text format
```

---

## Configuration

All settings load from environment variables or a `.env` file.

### Core

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | *(required)* | Groq API key |
| `DEBUG` | `false` | Enable SQLAlchemy query logging |
| `API_KEY` | `None` | Protect all endpoints with `X-API-Key` header (disabled in dev) |

### Database

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./docchat.db` | SQLAlchemy async DSN — use `postgresql+asyncpg://` for production |
| `DB_POOL_SIZE` | `10` | PostgreSQL connection pool size |
| `DB_MAX_OVERFLOW` | `20` | PostgreSQL max overflow connections |

### Storage

| Variable | Default | Description |
|---|---|---|
| `UPLOAD_DIR` | `./uploads` | Local upload directory (ignored when S3 is configured) |
| `MAX_UPLOAD_BYTES` | `10485760` | Maximum upload size (10 MB) |
| `S3_BUCKET` | `None` | S3 bucket name — enables S3 storage when set |
| `AWS_ACCESS_KEY_ID` | `None` | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | `None` | AWS credentials |
| `AWS_REGION` | `us-east-1` | AWS region |

### Chat & Retrieval

| Variable | Default | Description |
|---|---|---|
| `CHAT_MODEL` | `llama-3.3-70b-versatile` | Groq model ID |
| `CHAT_HISTORY_LIMIT` | `10` | Recent messages kept in LLM context |
| `HISTORY_SUMMARY_THRESHOLD` | `20` | Total messages before older ones are summarised |
| `RETRIEVAL_TOP_K` | `15` | Chunks retrieved before re-ranking |
| `RERANK_ENABLED` | `true` | Enable FlashRank cross-encoder re-ranking |
| `RERANK_TOP_K` | `5` | Chunks kept after re-ranking |
| `HYDE_ENABLED` | `false` | Embed a hypothetical answer for better semantic search |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | fastembed model name |
| `EMBEDDING_DIM` | `384` | Embedding vector dimension |

### Redis & Caching

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `None` | Redis DSN — enables ARQ workers, retrieval L2 cache, semantic cache |
| `SEMANTIC_CACHE_ENABLED` | `false` | Cache near-duplicate questions in Redis (requires `REDIS_URL`) |
| `SEMANTIC_CACHE_THRESHOLD` | `0.95` | Cosine similarity threshold for cache hits |

---

## Document lifecycle

```
pending → processing → ready
                    ↘ error
```

- **pending** — record created, ingestion queued
- **processing** — text being extracted, chunked, and embedded
- **ready** — chunks stored with embeddings; available for chat
- **error** — ingestion failed; `error_message` has details

Raw upload files are deleted (from disk or S3) once ingestion completes.

---

## Database schema

```
documents  ──< chunks         (document_id FK, indexed)
           ──< conversations  ──< messages
```

`chunks.embedding` stores raw float16 bytes (`numpy.ndarray.tobytes()`); the retrieval layer auto-detects float16 vs float32 by byte length. `chunks.page_number` and `chunks.section_heading` carry source metadata prefixed onto LLM context. All columns are added at startup via the auto-migration function — no manual schema changes needed when upgrading.

---

## Horizontal scaling

To run multiple instances behind a load balancer:

```env
DATABASE_URL=postgresql+asyncpg://user:pass@host/docchat
REDIS_URL=redis://localhost:6379
S3_BUCKET=my-docchat-bucket
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

Then start the ARQ worker alongside each web process:

```bash
arq app.workers.tasks.WorkerSettings
```

All instances share state via PostgreSQL (documents/conversations) and Redis (retrieval cache, semantic cache, job queue).
