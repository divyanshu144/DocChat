# Agentic DocChat — Design Spec
**Date:** 2026-05-04  
**Status:** Approved  
**Approach:** Deliberate migration  — keep what works, delete what gets replaced, add what's new

---

## Overview

Evolve DocChat from a single-document RAG app into a multi-source agentic research assistant. A LangGraph agent orchestrates retrieval across three source types (PDF, YouTube, Web), stores all vectors in ChromaDB, and traces every run through LangSmith. The existing DocChat codebase is the starting point — not a dependency, not a microservice.

LLM fine-tuning is explicitly out of scope for this phase. It is a separate future project.

---

## What Gets Kept

| File | Fate |
|---|---|
| `app/core/config.py` | Extended with ChromaDB, LangSmith, YouTube env vars |
| `app/core/database.py` | Unchanged — SQLite for conversation history only |
| `app/services/ingestion.py` | Moved to `app/services/ingestion/pdf.py`, output target changes to ChromaDB |
| `app/services/chat.py` | Groq client functions extracted to `app/services/llm.py` |
| `app/api/health.py` | Unchanged |
| `app/models/conversation.py` | Unchanged |

## What Gets Deleted

- `app/services/retrieval.py` — BM25 + cosine retrieval
- `app/services/reranker.py` — FlashRank cross-encoder
- `app/services/semantic_cache.py` — Redis semantic cache
- `app/services/storage.py` — aiofiles upload helper
- `app/services/embedder.py` — standalone embedder
- `app/api/documents.py` — old upload + listing endpoints
- `app/api/conversations.py` — old chat endpoints
- `app/workers/` — ARQ background task worker
- `app/core/security.py`, `app/core/limiter.py`, `app/core/metrics.py`
- `app/models/chunk.py`, `app/models/document.py`, `app/models/message.py`

---

## New Project Structure

```
app/
├── main.py                        # FastAPI app, registers routers
├── core/
│   ├── config.py                  # Pydantic Settings singleton (extended)
│   ├── database.py                # SQLite async engine (conversation history)
│   └── chroma.py                  # ChromaDB client singleton
├── api/
│   ├── health.py                  # GET /health (unchanged)
│   ├── ingest.py                  # POST /ingest/pdf, /ingest/youtube, /ingest/web
│   └── chat.py                    # POST /chat (SSE stream)
├── agent/
│   ├── graph.py                   # LangGraph StateGraph definition
│   ├── state.py                   # AgentState TypedDict
│   └── nodes/
│       ├── planner.py
│       ├── retriever.py
│       ├── synthesizer.py
│       └── critic.py
├── services/
│   ├── ingestion/
│   │   ├── pdf.py                 # DocChat parser reused, outputs to ChromaDB
│   │   ├── youtube.py             # YouTube transcript → chunks
│   │   └── web.py                 # Web scraper → chunks
│   └── llm.py                     # Groq client (generate_reply, generate_reply_stream)
└── models/
    └── conversation.py            # Unchanged

Dockerfile
docker-compose.yml
.env.example
```

---

## LangGraph Agent

### State

```python
class AgentState(TypedDict):
    query: str                    # original user question
    conversation_id: str          # links to SQLite conversation history
    sources_to_use: list[str]     # ["pdf", "youtube", "web"] — Planner sets this
    retrieved_chunks: list[dict]  # merged results from all queried sources
    answer: str                   # Synthesizer output
    critic_feedback: str          # Critic's note to Planner on retry
    needs_replan: bool            # True = Critic signals loop back to Planner
    iteration: int                # safety cap — max 2 loops total
```

### Nodes

**Planner**
- Reads: `query`, `critic_feedback` (if retrying), conversation history from SQLite
- Calls Groq once to decide which source types are relevant for this query
- On retry: rewrites `query` using `critic_feedback` to target what was missing
- Writes: `sources_to_use`

**Retriever** (hybrid)
- Reads: `sources_to_use`, `query`
- Loops over `sources_to_use`, calls the matching ChromaDB tool for each:
  - `search_pdf(query)` → queries `pdf_chunks` collection
  - `search_youtube(query)` → queries `youtube_chunks` collection
  - `search_web(query)` → queries `web_chunks` collection
- Merges and deduplicates results
- No LLM call — pure retrieval
- Writes: `retrieved_chunks`

**Synthesizer**
- Reads: `query`, `retrieved_chunks`, conversation history
- Calls Groq to generate a grounded answer citing chunk sources
- Writes: `answer`

**Critic**
- Reads: `query`, `retrieved_chunks`, `answer`
- Calls Groq to evaluate: is the answer grounded in chunks? Does it address the full question?
- If sufficient: sets `needs_replan=False`
- If insufficient: sets `needs_replan=True`, writes `critic_feedback`, increments `iteration`
- If `iteration >= 2`: sets `needs_replan=False` regardless (prevents infinite loop)
- Writes: `needs_replan`, `critic_feedback`, `iteration`

### Graph Edges

```
START → Planner → Retriever → Synthesizer → Critic
                                                ↓ needs_replan=False OR iteration≥2
                                               END
                                                ↓ needs_replan=True AND iteration<2
                                            Planner  (loop)
```

### LangSmith Tracing
- Each node is a named span in LangSmith
- ChromaDB queries inside Retriever are sub-spans
- Every Groq call is traced automatically via the LangSmith SDK
- One agent run = one LangSmith trace, inspectable end-to-end
- Configured via `LANGSMITH_API_KEY` + `LANGSMITH_PROJECT` env vars

---

## ChromaDB

### Collections

**`pdf_chunks`**
```
document:  chunk text (with page/section prefix, e.g. "[Page 3, Section "Introduction"] ...")
metadata:  source_id, filename, page_number, section_heading, chunk_index, ingested_at
```

**`youtube_chunks`**
```
document:  transcript chunk text
metadata:  video_id, video_url, title, channel, timestamp_start, timestamp_end, chunk_index, ingested_at
```

**`web_chunks`**
```
document:  scraped text chunk
metadata:  url, title, domain, chunk_index, scraped_at
```

All collections use `fastembed BAAI/bge-small-en-v1.5` (384-dim) — same model as DocChat v1.

### Client
`app/core/chroma.py` exposes a singleton `get_chroma_client()` that connects to ChromaDB over HTTP (`CHROMA_HOST:CHROMA_PORT`). In Docker this is the `chromadb` service; locally it can run in-memory for development.

---

## Ingestion

### PDF (`services/ingestion/pdf.py`)
- DocChat's pymupdf + pytesseract extractor moved here verbatim
- Sentence-aware chunking and page/section heading metadata kept
- Output: chunks stored in `pdf_chunks` ChromaDB collection (not SQLite)

### YouTube (`services/ingestion/youtube.py`)
- Fetches transcript via `youtube-transcript-api`
- Fetches title + channel via `pytube`
- Chunks transcript into overlapping ~300-token windows, preserving timestamp range per chunk
- Output: chunks stored in `youtube_chunks` with `timestamp_start`/`timestamp_end` for citation

### Web (`services/ingestion/web.py`)
- Fetches page via `httpx`
- Extracts main article content via `trafilatura` (handles boilerplate removal)
- Chunks with `langchain-text-splitters` (already in deps)
- Output: chunks stored in `web_chunks`

---

## API Endpoints

All routes under `/api/v1` prefix.

```
GET  /health                        health check (unchanged)

POST /api/v1/ingest/pdf             multipart upload, returns source_id
POST /api/v1/ingest/youtube         body: { url: str }, returns source_id
POST /api/v1/ingest/web             body: { url: str }, returns source_id

GET  /api/v1/sources                list all ingested sources across all collections
DELETE /api/v1/sources/{source_id}  delete source + all its chunks from ChromaDB

POST /api/v1/chat                   body: { query, conversation_id?, sources? }
                                    returns: SSE stream of agent answer tokens
```

---

## Docker & Deployment

### `docker-compose.yml`
```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - chromadb
    volumes:
      - ./data:/app/data

  chromadb:
    image: chromadb/chroma:latest
    ports:
      - "8001:8000"
    volumes:
      - ./chroma_data:/chroma/chroma
```

### `Dockerfile`
```dockerfile
FROM python:3.13-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Required `.env` Variables
```
GROQ_API_KEY=
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=docchat-agent
CHROMA_HOST=chromadb
CHROMA_PORT=8000
YOUTUBE_API_KEY=          # optional
```

---

## New Dependencies

```
chromadb
youtube-transcript-api
pytube
trafilatura
httpx
langsmith
langgraph
langchain-core
```

---

## CLAUDE.md Update

To be done as the final step of implementation. Sections to rewrite:
- **Project Overview** — agentic multi-source RAG, not "document-based chat skeleton"
- **Commands** — add `docker-compose up`, LangSmith env vars, ChromaDB notes
- **Architecture** — replace old file descriptions with new structure

Workflow Orchestration, Task Management, and Core Principles sections remain unchanged.

---

## Out of Scope

- LLM fine-tuning — separate future phase
- Critic loop beyond 2 iterations
- Authentication / rate limiting
- Prometheus metrics (replaced by LangSmith for this version)
- ARQ background workers (ingestion is synchronous in v1)
