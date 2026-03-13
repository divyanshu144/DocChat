# DocChat Codebase Audit

**Date:** 2026-03-08
**Auditor:** Senior Engineer Review
**Scope:** Full codebase — all `.py` files, static frontend, requirements, and DB migrations
**Revision:** v3 (re-verified against current source; 2 new bugs added)

---

## 1. Executive Summary

DocChat is a well-structured FastAPI RAG application with a solid hybrid retrieval pipeline
(BM25 + semantic + RRF + cross-encoder re-ranking). Concerns are well-separated, optional
features (HyDE, semantic cache, ARQ queue) degrade gracefully, and the DB migration strategy
is idempotent. The frontend is clean and functional.

However, **two bugs will visibly corrupt LLM output** in normal usage (newline-in-token SSE
framing and LLM reply of `None`), and the semantic cache is wired in the wrong order,
defeating its primary purpose. Several medium-severity issues also exist. Nine total bugs are
documented below, followed by five prioritised roadmap features.

---

## 2. Feature-by-Feature Correctness Review

### 2.1 Document Upload & Ingestion

| Feature | Status | Notes |
|---|---|---|
| PDF extraction (pymupdf primary) | Working | Per-page heading detection via largest-font span |
| PDF OCR fallback (pytesseract) | Working | Triggered only on blank pages |
| PDF text fallback (pypdf) | Working | No heading detection; acceptable degradation |
| DOCX extraction | Working | Groups paragraphs by Heading style correctly |
| Plain-text extraction | Working | UTF-8 with `errors="replace"` |
| Sentence-aware chunking | Working | `RecursiveCharacterTextSplitter`, good separator list |
| Float16 embedding storage | Working | Auto-detect on load; negligible cosine-sim loss |
| Background ingestion (BackgroundTasks) | Working | Session isolation via new `AsyncSessionLocal` is correct |
| ARQ queue ingestion path | Logic correct, pool leak | See Bug #5 |
| Content-type validation | Working | Pre-save check against `SUPPORTED_TYPES` |
| File size validation | Working with caveat | File fully written before check; see Bug #4 |
| `_chunk_segments` on event loop | Bug | Blocks async loop for large documents; see Bug #3 |

### 2.2 Retrieval

| Feature | Status | Notes |
|---|---|---|
| BM25 with NLTK stemming | Working | Graceful fallback to `lower().split()` |
| Semantic retrieval (fastembed) | Working | Float16 auto-detection correct for bge-small 384-dim |
| RRF fusion (k=60) | Working | Correct implementation |
| LRU cache (maxsize=50) | Working | Invalidation on re-ingestion correct |
| Metadata-prefixed chunk output | Working | `[Page N, Section "X"]` applied before LLM |

### 2.3 Re-ranking

| Feature | Status | Notes |
|---|---|---|
| FlashRank cross-encoder | Working | Runs in executor; correct graceful fallback |
| Fallback when flashrank missing | Working | Returns `chunks[:top_k]` unranked |

### 2.4 Chat & Conversations

| Feature | Status | Notes |
|---|---|---|
| Sync chat endpoint | Mostly working | `message.content` may be `None`; see Bug #1 |
| Streaming chat (SSE) | Broken for structured output | Newline-in-token drops content; see Bug #2 |
| HyDE query expansion | Working | Correct opt-in; error is swallowed gracefully |
| History summarization | Working | Threshold logic and ordering are correct |
| `is_complete=False` placeholder | Working | Prevents corrupted history after dropped connection |
| Orphaned incomplete messages | Architectural gap | Never cleaned up on restart; see §4.5 |
| Semantic cache lookup order | Wrong — defeats purpose | See Bug #6 |
| `get_conversation` exposes incomplete msgs | Bug | `selectinload` returns all messages including `is_complete=False` |

### 2.5 Frontend

| Feature | Status | Notes |
|---|---|---|
| Document upload + status polling | Working | 1500ms polling, clears on ready/error |
| Conversation create | Working | |
| Streaming chat display | Broken for multi-line content | Shares Bug #2 |
| Past conversations list | Working | |
| Resume conversation | Working | |
| Download chat as Markdown | Working | |
| Health check display | Cosmetic bug | Checks `=== "ok"` but API returns `"healthy"`; see Bug #8 |

### 2.6 Infrastructure

| Feature | Status | Notes |
|---|---|---|
| WAL mode (SQLite) | Working | Set via sync engine connect event |
| DB migration on startup | Working | Idempotent `ALTER TABLE` / `PRAGMA table_info` |
| Prometheus metrics | Working | All key pipeline stages instrumented |
| Lifespan model pre-warming | Working | Embedder and ranker loaded at startup |
| Request logging middleware | Working | `x-request-id` propagation correct |

---

## 3. Bugs

### Bug #1 — CRITICAL: `generate_reply` may return `None` and crash downstream

**File:** `app/services/chat.py:41`
**Also:** `generate_reply_stream` line 55

```python
return response.choices[0].message.content  # content can be None
```

The Groq API (following the OpenAI spec) sets `message.content = None` when
`finish_reason` is `"tool_calls"` or when the model returns a function call. If
this happens, the `answer` variable in the sync endpoint is `None`, and
`"".join(full_reply)` in the stream path will raise `TypeError` the moment
`msg.content = "".join(full_reply)` tries to write to the DB (content column is
`NOT NULL Text`).

Even without tool-call edge cases, Groq occasionally returns `None` content on
rate-limit or partial completions.

**Fix:**
```python
# chat.py — generate_reply
content = response.choices[0].message.content
return content or ""

# generate_reply_stream
delta = chunk.choices[0].delta.content
if delta:  # already guards None, but also guard empty string
    yield delta
```

---

### Bug #2 — CRITICAL: SSE streaming silently drops content containing newlines

**File:** `app/api/conversations.py:358`
**Also:** `app/static/app.js:270–276`

```python
# Server emits:
yield f"data: {token}\n\n"
```

The SSE protocol uses `\n\n` as the **event terminator**. If a LLM token is
`"Step 1:\nDo this"`, the emitted bytes are:

```
data: Step 1:
Do this

```

The client parser splits on `\n` and only processes lines starting with `data:`.
The line `"Do this"` has no `data:` prefix and is silently discarded. Any LLM
response containing code blocks, numbered lists, or multi-paragraph text will be
visibly corrupted.

**Fix — Option A (simplest, requires client decode):**
```python
# server
safe = token.replace("\n", "\\n")
yield f"data: {safe}\n\n"

# client app.js
else { assistantEl.textContent += token.replace(/\\n/g, "\n"); ... }
```

**Fix — Option B (SSE spec-compliant, no client change):**
```python
lines = token.split("\n")
yield "".join(f"data: {l}\n" for l in lines) + "\n"
```

---

### Bug #3 — HIGH: `generate_reply` returns `None` unguarded in sync endpoint

(Covered under Bug #1 — same root cause, separate call site.)

---

### Bug #3 — HIGH: `_chunk_segments` runs synchronously on the event loop

**File:** `app/services/ingestion.py:187`

```python
segments = await loop.run_in_executor(None, _extract_segments, ...)
raw_chunks = _chunk_segments(segments)   # ← runs on event loop thread
```

`_chunk_segments` calls `RecursiveCharacterTextSplitter.split_text()` for every
segment. For a 200-page PDF this can take 200–600ms, blocking all other in-flight
requests for the duration.

**Fix:**
```python
raw_chunks = await loop.run_in_executor(None, _chunk_segments, segments)
```

---

### Bug #4 — HIGH: `get_conversation` returns incomplete (in-flight) messages

**File:** `app/api/conversations.py:393–401`

```python
result = await db.execute(
    select(Conversation)
    .where(Conversation.id == conversation_id)
    .options(selectinload(Conversation.messages))  # loads ALL messages
)
```

`selectinload` fetches every `Message` row, including rows with
`is_complete=False` (empty streaming placeholders). The API response then
exposes `{"content": "", "role": "assistant"}` entries to the client. The
frontend's `filter(m => m.content)` masks this, but the API contract is wrong
and can confuse any other consumer.

**Fix:** Filter `is_complete=True` in the query, or add a custom loader that
applies the filter before loading the relationship.

---

### Bug #5 — MEDIUM: File fully written to disk before size limit is checked

**File:** `app/api/documents.py:68–75`

```python
file_path = await storage.save_upload(file)    # entire file streamed to disk
file_size = Path(file_path).stat().st_size
if file_size > settings.max_upload_bytes:
    storage.delete_file(file_path)             # can silently fail (OSError)
    raise HTTPException(413, ...)
```

A 500 MB PDF is fully written before being rejected, wasting disk I/O. The
`delete_file` on the rejection path also swallows `OSError`, meaning orphaned
files can remain in `uploads/` indefinitely.

**Fix:** Stream with a byte counter in `save_upload` and raise `ValueError` when
`max_upload_bytes` is exceeded. Check the `Content-Length` header first for a
fast pre-rejection of obviously oversized requests.

---

### Bug #6 — MEDIUM: Semantic cache checked after retrieval — defeats its purpose

**Files:** `app/api/conversations.py:262–276` (sync), `:314–333` (stream)

```python
# Current — WRONG order
chunks, query_emb = await _run_retrieval_pipeline(...)   # always runs
sc = get_semantic_cache()
if sc is not None:
    cached = await sc.get(query_emb, ...)                # checked too late
```

The semantic cache's purpose is to skip retrieval **and** the LLM when a
semantically similar query was answered recently. In the current order it only
skips the LLM call (~50% latency saved instead of ~95%).

**Fix:** Embed the query first, check the cache, and only run the full pipeline
on a miss:
```python
query_emb = await retrieval.embed_query(body.question)
sc = get_semantic_cache()
if sc is not None and query_emb is not None:
    cached = await sc.get(query_emb, conversation.document_id)
    if cached is not None:
        # store messages, return cached
        ...
# cache miss — run full pipeline, pass pre-computed embedding
chunks, _ = await _run_retrieval_pipeline(..., query_emb=query_emb)
```

---

### Bug #7 — MEDIUM: ARQ Redis connection pool is never closed

**File:** `app/api/documents.py:47–51`

```python
pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
await pool.enqueue_job("ingest_document_task", document_id)
# pool.aclose() never called
```

Every document upload via the ARQ path opens a new Redis connection pool and
leaks it. Under load this exhausts file descriptors.

**Fix:** `async with create_pool(...) as pool:` or hold a module-level singleton
pool initialised in the lifespan handler.

---

### Bug #8 — MEDIUM: `redis[asyncio]` missing from `requirements.txt`

**File:** `requirements.txt`, `app/services/semantic_cache.py:25`

Enabling `SEMANTIC_CACHE_ENABLED=true` + `REDIS_URL` will immediately raise
`ImportError: No module named 'redis'` because the `redis` package is not listed
as a dependency.

**Fix:** Add `redis[asyncio]>=5.0.0` to `requirements.txt`.

---

### Bug #9 — LOW: Semantic cache FIFO eviction is actually random

**File:** `app/services/semantic_cache.py:64–68`

```python
fields = await self._client.hkeys(key)
if fields:
    await self._client.hdel(key, fields[0])
```

Redis hash keys are unordered. `HKEYS` returns fields in an **arbitrary** order,
not insertion order. The comment and intent say "FIFO eviction" but the actual
behaviour is random eviction. For a correctness-sensitive cache this is a
misleading contract.

**Fix:** Use a Redis Sorted Set (score = unix timestamp) to maintain insertion
order, or accept that it is random and update the comment.

---

### Bug #10 — LOW: Health check status value mismatch

**File:** `app/api/health.py:13`, `app/static/app.js:63`

```python
# API returns:  {"status": "healthy", ...}
# JS checks:    data.status === "ok" ? "Healthy" : data.status
# Result:       always displays lowercase "healthy"
```

**Fix:** Either change `health.py` to return `"ok"`, or change `app.js` to check
`=== "healthy"`.

---

### Bug #11 — LOW: `debug: bool = True` default echoes SQL in production

**File:** `app/core/config.py:16`

`debug=True` passes `echo=True` to `create_async_engine`, printing every SQL
statement to stdout. This degrades performance, pollutes logs, and can expose
query parameters in production.

**Fix:** Change default to `debug: bool = False`.

---

### Bug #12 — LOW: `np.ndarray` forward reference without module-level import

**File:** `app/api/conversations.py:135`

```python
async def _run_retrieval_pipeline(
    ...) -> tuple[list[str], "np.ndarray | None"]:
```

`numpy` is only imported inside the function body (`import numpy as np` on
line 137), not at module scope. The string annotation `"np.ndarray | None"`
resolves to `None` under `get_type_hints()`, breaking mypy and any tooling that
evaluates annotations.

**Fix:** Add `import numpy as np` at module level, or use
`from __future__ import annotations`.

---

### Bug #13 — MEDIUM: History summarization injects a second system message

**File:** `app/api/conversations.py:117–120`, `app/services/chat.py:26–31`

When `total > history_summary_threshold`, `_load_history` prepends a system
message to the history list:

```python
history = [
    {"role": "system", "content": f"Earlier conversation summary: {summary}"}
] + history
```

`_build_messages` then wraps this history between **another** system message
(the RAG context prompt) and the new user turn:

```python
return [
    {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
    *history,     # ← contains a second system message
    {"role": "user", "content": question},
]
```

The OpenAI/Groq spec requires the system message to be the **first** turn only.
Groq's llama-3.3 currently accepts this, but it is undefined behaviour and can
confuse the model about which instructions take precedence, causing partial
instruction-following or hallucinated format violations.

**Fix:** Merge the summary into the RAG system prompt rather than injecting it
as a separate system turn:

```python
# In _load_history, return the summary string separately
return history, summary  # where summary is str | None

# In _build_messages / callers, inject it into SYSTEM_PROMPT
context_block = SYSTEM_PROMPT.format(context=context)
if summary:
    context_block += f"\n\nEarlier conversation summary: {summary}"
```

---

### Bug #14 — MEDIUM: `Conversation.messages` relationship uses invalid `order_by` string

**File:** `app/models/conversation.py:24`

```python
messages: Mapped[list["Message"]] = relationship(
    "Message",
    back_populates="conversation",
    cascade="all, delete-orphan",
    order_by="messages.c.created_at",   # ← string, not ORM expression
)
```

In SQLAlchemy 2.x with `DeclarativeBase` and `mapped_column`, the recommended
form for relationship `order_by` is the ORM column attribute, not a Core table
string. The string `"messages.c.created_at"` triggers an internal string-eval
path that may resolve differently across SQLAlchemy patch versions, and emits
a `SAWarning` in test output. If it silently fails, messages are returned in
undefined DB-scan order — which happens to match insertion order on SQLite but
is not guaranteed.

**Fix:**
```python
from app.models.message import Message  # import at bottom of file to avoid circular

messages: Mapped[list["Message"]] = relationship(
    "Message",
    back_populates="conversation",
    cascade="all, delete-orphan",
    order_by="Message.created_at",   # ORM class attribute string form
)
```

Or better, use a `lazy="selectin"` + explicit query order in the endpoint rather
than a relationship-level order.

---

## 4. Architecture Observations

### 4.1 No DELETE Endpoints

There is no `DELETE /documents/{id}` or `DELETE /conversations/{id}`. Documents
accumulate indefinitely (file is deleted post-ingestion but the DB record
remains). The SQLAlchemy models already define `cascade="all, delete-orphan"`, so
adding these endpoints is straightforward.

### 4.2 No Authentication

Every endpoint is publicly accessible. A single-user localhost deployment is
fine, but sharing the server with anyone exposes all documents and conversations
and risks Groq API quota exhaustion.

### 4.3 Orphaned Incomplete Messages

If the server restarts mid-stream, assistant messages with `is_complete=False`
accumulate in the database and are never cleaned up. A startup migration that
marks orphaned incomplete messages as failed (or deletes them) would prevent
DB bloat.

### 4.4 Conversation Has No Title or Name

`Conversation` only stores `document_id` and `created_at`. Multiple conversations
for the same document cannot be distinguished by users beyond their timestamp.

### 4.5 `max_tokens=1024` Hardcoded

Both `generate_reply` and `generate_reply_stream` hardcode `max_tokens=1024`.
Responses to complex questions about long documents frequently hit this ceiling
mid-sentence. This should be a `settings.chat_max_tokens` field.

### 4.6 Linear Semantic Cache Scan

`SemanticCache.get` iterates over **all** cached entries for a document
(`hgetall` → loop) to find the best cosine match. At `_MAX_ENTRIES_PER_DOC=200`
this is 200 deserialise-and-dot-product operations per query. For high-traffic
documents this becomes a bottleneck. A vector store (Redis Stack with
`FT.SEARCH`) would reduce this to a single ANN query.

### 4.7 No Re-ingestion / Retry Endpoint

If ingestion fails (status `error`), the raw uploaded file has already been
deleted (`delete_file` is called in the error path too). There is no way to retry
without re-uploading.

### 4.8 No Message Index on `conversations` Table

Queries against `messages` filter on `conversation_id` and `created_at`. There
is no index on `messages.conversation_id`, meaning every history load does a full
table scan. For a DB with many messages, this degrades significantly.

---

## 5. Five Most Impactful Features to Build Next

### Feature 1 — Source Citations in Answers

**Impact: High — the single biggest trust and usability improvement**

Chunks sent to the LLM already carry `[Page N, Section "X"]` prefixes, but this
metadata is stripped from the user-facing answer. Without citations, users have
no way to verify answers; with them, the tool is genuinely useful for legal,
research, and compliance work.

**Implementation sketch:**
- Update `SYSTEM_PROMPT` to instruct the model to keep `[Page N]` markers inline.
- Add `citations: list[Citation]` to `ChatResponse` where
  `Citation = {page: int | None, section: str | None, snippet: str}`.
- After generation, parse `[Page N]` markers from the raw reply, extract surrounding
  text as the snippet, and populate the `citations` list.
- Render citations as numbered footnotes or a collapsible "Sources" panel in the
  frontend. Clicking a citation could highlight the matching page/section.

**Why it matters:** Grounded, verifiable answers are the core value proposition
of a RAG system. This is the feature that separates a demo from a production tool.

---

### Feature 2 — Document & Conversation Deletion

**Impact: High — required for any real deployment**

Without deletion, the system is a one-way ratchet. Documents accumulate, DB
grows, and users cannot clean up mistakes or expired content.

**Implementation sketch:**
- `DELETE /api/v1/documents/{document_id}` — cascade-deletes chunks and
  conversations (already modeled), calls `invalidate_bm25(document_id)`, and
  removes any semantic cache entries for the document.
- `DELETE /api/v1/conversations/{conversation_id}` — deletes messages and the
  conversation row.
- Guard `DELETE /documents/{id}` against `status=processing` (reject with 409).
- Add a trash icon per document/conversation in the frontend with a confirm dialog.

**Why it matters:** GDPR, storage management, and basic UX hygiene. Without this,
the system cannot be used beyond a short-lived demo.

---

### Feature 3 — API Key Authentication

**Impact: High — prerequisite for sharing with anyone**

Every endpoint is currently public. Any user who can reach the server can read
all documents and conversations, exhaust Groq quota, and exfiltrate data.

**Implementation sketch:**
- Add `api_key: str | None` to `Settings` (env var `API_KEY`).
- Write a FastAPI `Security` dependency that reads `Authorization: Bearer <key>`
  or `X-API-Key: <key>` and raises `401`/`403` as appropriate.
- Apply the dependency as a router-level dependency (exclude `/health` and
  `/metrics`).
- For multi-user: store keys in a `users` DB table; scope documents and
  conversations to the owning key.
- Add the `Authorization` header to all frontend `fetch` calls, reading the key
  from `localStorage` or a login form.

**Why it matters:** Every other feature is irrelevant if the server is open to
the world. Auth is the load-bearing wall.

---

### Feature 4 — Multi-Document Conversations

**Impact: Medium-High — enables the most common real-world RAG use cases**

Today every conversation is locked to one document. Users who want to compare a
contract against a policy, or cross-reference multiple research papers, cannot
do so.

**Implementation sketch:**
- Add a `conversation_documents` join table (columns: `conversation_id`,
  `document_id`) to replace the single `document_id` FK on `Conversation`.
  Alternatively, store `document_ids` as a JSON column for SQLite simplicity.
- Update `ConversationCreate` to accept `document_ids: list[str]`.
- Update `retrieve_chunks` to accept `document_ids: list[str]`, load chunk
  caches for all IDs, and merge their RRF ranked lists.
- Prefix chunk text with `[Doc: {filename}, Page N]` so the LLM can attribute
  answers to specific documents.
- Update the frontend "Create conversation" flow to allow selecting multiple
  documents from a dropdown or checkbox list.

**Why it matters:** Single-document chat is the MVP. Multi-document is the product.

---

### Feature 5 — Real-Time Ingestion Progress via SSE

**Impact: Medium — significant UX improvement for large files**

The current UI polls every 1500ms with no indication of progress beyond
"processing". For large PDFs (50+ pages, 10+ MB), users stare at a status badge
for 30+ seconds with no feedback.

**Implementation sketch:**
- Add an `asyncio.Queue` per `document_id` in a module-level dict, or use Redis
  pub/sub when `REDIS_URL` is set.
- Emit progress events from `ingest_document` at each pipeline stage:
  `{stage: "extracting", page: 5, total_pages: 42}`,
  `{stage: "chunking", chunks_done: 80}`,
  `{stage: "embedding", chunks_done: 60, total: 80}`,
  `{stage: "done"}`.
- Add `GET /api/v1/documents/{document_id}/progress` as an SSE endpoint that
  reads from the queue and streams these events.
- Replace the polling loop in the frontend with an `EventSource` that drives a
  progress bar with stage labels.

**Why it matters:** For large documents, the current UX is a black box. Progress
feedback reduces perceived wait time and eliminates unnecessary HTTP polling.

---

## 6. Summary Tables

### Bugs

| # | File | Severity | Description |
|---|---|---|---|
| 1 | `services/chat.py:41` | **Critical** | `message.content` can be `None`; crashes DB write |
| 2 | `api/conversations.py:358` | **Critical** | Newline tokens break SSE framing; content silently dropped |
| 3 | `services/ingestion.py:187` | **High** | `_chunk_segments` blocks event loop |
| 4 | `api/conversations.py:393` | **High** | `get_conversation` exposes `is_complete=False` messages |
| 5 | `api/documents.py:68` | **Medium** | Full file written before size check; orphaned file on OSError |
| 6 | `api/conversations.py:262` | **Medium** | Semantic cache checked after retrieval; saves only LLM call |
| 7 | `api/documents.py:49` | **Medium** | ARQ Redis pool never closed; leaks connections |
| 8 | `requirements.txt` | **Medium** | `redis[asyncio]` missing; `ImportError` when cache enabled |
| 9 | `services/semantic_cache.py:64` | **Low** | "FIFO" eviction is actually random (`hkeys` is unordered) |
| 10 | `api/health.py`, `static/app.js:63` | **Low** | Status mismatch: API returns `"healthy"`, JS checks `"ok"` |
| 11 | `core/config.py:16` | **Low** | `debug=True` default echoes all SQL in production |
| 12 | `api/conversations.py:135` | **Low** | `"np.ndarray"` annotation without module-level `numpy` import |
| 13 | `api/conversations.py:117`, `services/chat.py:26` | **Medium** | History summarization injects a second system message |
| 14 | `models/conversation.py:24` | **Medium** | `order_by="messages.c.created_at"` is an invalid SQLAlchemy 2.x string form |

### Roadmap Features (Priority Order)

| # | Feature | Effort | Impact |
|---|---|---|---|
| 1 | Source citations in answers | Medium | High |
| 2 | Document & conversation deletion | Low | High |
| 3 | API key authentication | Medium | High |
| 4 | Multi-document conversations | High | Medium-High |
| 5 | Real-time ingestion progress (SSE) | Medium | Medium |
