# Skill Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic CLAUDE.md with a keyword-driven resolver + two domain skill files + one conventions file so Claude loads only relevant context per task.

**Architecture:** RESOLVER.md at project root holds a keyword → skill-file routing table. Three new files carry domain depth carved out of CLAUDE.md. CLAUDE.md shrinks to a ~60-line orientation skeleton. No code changes — this is pure developer tooling.

**Tech Stack:** Markdown, Claude Code skill system, existing `.claude/skills/` convention.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `RESOLVER.md` | Keyword routing table + loading rules |
| Create | `.claude/skills/conventions.md` | Cross-cutting patterns: settings, get_db, get_embedder, async, API prefix |
| Create | `.claude/skills/langgraph/SKILL.md` | AgentState, node contracts, critic loop, failure modes |
| Create | `.claude/skills/ingestion/SKILL.md` | ChromaDB collections, chunking, ARQ, source ID, startup dep |
| Modify | `CLAUDE.md` | Trim to skeleton; add RESOLVER.md reference at top |

---

## Task 1: Create RESOLVER.md

**Files:**
- Create: `RESOLVER.md`

- [ ] **Step 1: Create the file**

Write `RESOLVER.md` at the project root with the following content:

```markdown
# RESOLVER.md

Scan the task description and current file context for the keywords below.
Load the matching skill file **before** responding. This file is loaded automatically
at session start via the CLAUDE.md reference.

## Routing Table

| Keywords | Skill file | Load when |
|----------|-----------|-----------|
| `agent` `graph` `node` `critic` `planner` `retriever` `synthesizer` `AgentState` `replan` `LangGraph` | `.claude/skills/langgraph/SKILL.md` | Touching the agent pipeline |
| `ingest` `pdf` `youtube` `web` `chroma` `embed` `chunk` `collection` `source_id` | `.claude/skills/ingestion/SKILL.md` | Touching data ingestion or ChromaDB |
| `settings` `config` `get_db` `SQLAlchemy` `async` `session` `engine` `dependency` `lifespan` `startup` `middleware` | `.claude/skills/conventions.md` | Touching shared infrastructure |

## Loading Rules

1. **Load at most 2 files per response** — primary domain skill + `conventions.md` if infrastructure keywords are also present.
2. **Primary domain = most keyword matches.** Tie → use the domain whose files are being edited.
3. **When the 2-file cap drops a relevant domain skill**, say at the top of the response: "Note: this task also touches [domain] — invoke `/[skill]` if you need that context."
4. **No keyword match** → proceed with CLAUDE.md context only.
5. **Process skills are never auto-loaded** — `fde-plan`, `fde-review`, `api-conventions`, `debug-playbook`, `pr-checklist` are user-invoked only.

## Growth Rules

- Add a keyword row when a new domain skill is created. Grep for false-positive matches before committing.
- Promote `.claude/skills/conventions.md` to a folder if it exceeds ~200 lines or a third domain with different convention needs appears.
- Duplication between a process skill and `conventions.md` is acceptable — the trigger mechanism difference justifies it.
```

- [ ] **Step 2: Verify**

```bash
wc -l RESOLVER.md
head -5 RESOLVER.md
```

Expected: file exists, first line is `# RESOLVER.md`.

---

## Task 2: Create `.claude/skills/conventions.md`

**Files:**
- Create: `.claude/skills/conventions.md`

- [ ] **Step 1: Create the file**

```markdown
# DocChat — Cross-Cutting Conventions

Auto-loaded by RESOLVER.md when infrastructure keywords are detected.
Do not invoke this directly — it is loaded automatically alongside the primary domain skill.

---

## `settings` Singleton

Always import from `app.core.config`:

```python
from app.core.config import settings
```

Never access `os.environ` directly for app config. All fields are pydantic-validated,
`.env`-loaded, and test-overridable via `get_settings.cache_clear()` + monkeypatching.
The singleton is an `lru_cache`-wrapped factory — one `Settings` instance per process.

Key fields: `settings.api_prefix` (`/api/v1`), `settings.database_url`,
`settings.groq_api_key`, `settings.embedding_model`, `settings.chroma_host/port`,
`settings.langsmith_api_key`.

---

## `get_db()` Async Session

Use only as a FastAPI dependency:

```python
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from app.core.database import get_db

async def my_endpoint(db: AsyncSession = Depends(get_db)):
    result = await db.execute(...)
```

Never construct `AsyncSessionLocal()` directly outside of `get_db()`.
The context manager handles commit/rollback/close — constructing it manually leaks connections.

---

## `get_embedder()` Singleton

```python
from app.services.embedder import get_embedder

embedder = get_embedder()   # _Embedder | None
if not embedder:
    return []               # always guard — returns None on fastembed import failure
```

- Model: `BAAI/bge-small-en-v1.5` ONNX (384-dim, float32 output)
- First call: ~2s warm-up (ONNX model download on first run, then cached to `~/.cache/huggingface/`)
- **Do not reinitialize.** The module-level `_embedder_instance` is a singleton.
  Calling `get_embedder()` again returns the same object. Creating a second `_Embedder`
  instance is not supported and will double memory usage.
- Returns `None` if fastembed is not installed or fails to load (graceful degradation).
- Used by: `app/services/ingestion/pdf.py`, `youtube.py`, `web.py`, and `app/agent/nodes/retriever.py`.

---

## Async Invariants

All I/O paths are `async`. Never call blocking code in a coroutine:

```python
# CPU-bound sync work → offload to thread
import asyncio
result = await asyncio.get_running_loop().run_in_executor(None, sync_fn, arg)

# I/O-bound → native async
async with session.begin():
    await session.execute(...)
```

Known violation: `_chunk_segments()` in `app/services/ingestion/pdf.py` calls synchronous
text splitting inside an async path (Bug #3 from the audit). Fix with `run_in_executor`
when addressing that bug — do not replicate the pattern elsewhere.

---

## API Prefix

Always use `settings.api_prefix` — never hardcode `"/api/v1"`.

```python
# main.py — correct pattern
app.include_router(router, prefix=settings.api_prefix, tags=["Folders"])

# router file — declare routes without prefix
@router.get("/folders")        # NOT @router.get("/api/v1/folders")
@router.post("/folders", status_code=201)
```

`main.py` adds the prefix at include time. Router modules are prefix-agnostic.
```

- [ ] **Step 2: Verify**

```bash
wc -l .claude/skills/conventions.md
grep -c "^##" .claude/skills/conventions.md
```

Expected: file exists, 5 `##` section headers.

---

## Task 3: Create `.claude/skills/langgraph/SKILL.md`

**Files:**
- Create: `.claude/skills/langgraph/SKILL.md`

- [ ] **Step 1: Create the directory and file**

```bash
mkdir -p .claude/skills/langgraph
```

Write `.claude/skills/langgraph/SKILL.md`:

```markdown
# LangGraph Agent — Domain Skill

Auto-loaded by RESOLVER.md when agent/graph/node/critic/planner/retriever/synthesizer/
AgentState/replan/LangGraph keywords are detected.

---

## AgentState

`TypedDict` in `app/agent/state.py`. All nodes read from and write partial dicts back into it.
LangGraph merges returned dicts — nodes only return the keys they write.

| Field | Type | Written by | Meaning |
|-------|------|-----------|---------|
| `query` | `str` | planner (may rewrite) | Current query; planner rewrites it on replan to address critic feedback |
| `conversation_id` | `str` | chat API (before invoke) | SQLite conversation ID — not used inside the graph, passed through for context |
| `sources_to_use` | `list[str]` | planner | Which collections to query: `"pdf"`, `"youtube"`, `"web"` |
| `retrieved_chunks` | `list[dict]` | retriever | Each chunk: `{text, metadata, source_type, distance}` |
| `answer` | `str` | synthesizer | Final answer with inline citations |
| `critic_feedback` | `str` | critic | One sentence on what was missing; empty string if quality=good |
| `needs_replan` | `bool` | critic | `True` → `_route_critic` sends state back to planner |
| `iteration` | `int` | critic | Incremented at top of each critic pass; cap is 2 |

---

## Node Contracts

### `planner_node` — `app/agent/nodes/planner.py`

**Reads:** `query`, `critic_feedback`
**Writes:** `sources_to_use`, `query` (rewrites on replan)

Calls Groq with a JSON-only prompt asking which of `["pdf", "youtube", "web"]` to search
and optionally rewrites the query to address critic feedback. On JSON parse failure:
defaults to all three sources + original query unchanged. Never raises — always returns a dict.

### `retriever_node` — `app/agent/nodes/retriever.py`

**Reads:** `query`, `sources_to_use`
**Writes:** `retrieved_chunks`

Embeds `query` via `get_embedder()`. If embedder is None: returns `{"retrieved_chunks": []}`.
Queries each ChromaDB collection in `sources_to_use` independently (N_RESULTS=5 each).
Deduplicates chunks on exact `text` match. Never raises on per-collection errors — catches
and continues, so one failed collection does not abort the others.

Collection mapping: `{"pdf": "pdf_chunks", "youtube": "youtube_chunks", "web": "web_chunks"}`.

### `synthesizer_node` — `app/agent/nodes/synthesizer.py`

**Reads:** `query`, `retrieved_chunks`
**Writes:** `answer`

Builds a context block via `_format_chunks()` with inline citation labels:
- PDF: `[PDF — filename.pdf p.3]`
- YouTube: `[YouTube — Video Title @120s]`
- Web: `[Web — example.com]`

Then calls `chat_complete()` with a system prompt instructing citation and no hallucination.
Known bug (Bug #1): if `chat_complete()` returns `None`, `answer` will be `None` and the
subsequent DB write in `chat.py` will crash. Not yet fixed.

### `critic_node` — `app/agent/nodes/critic.py`

**Reads:** `answer`, `query`, `iteration`
**Writes:** `needs_replan`, `critic_feedback`, `iteration`

Increments `iteration` first. If `iteration >= 2`: short-circuits immediately, returns
`{"needs_replan": False, "iteration": iteration, "critic_feedback": ""}` — no LLM call.
Otherwise: calls Groq asking for `{"quality": "good"|"poor", "feedback": "..."}`.
On parse failure: defaults to `quality="good"` (safe fallback, does not replan).

---

## Replan Loop

```
planner → retriever → synthesizer → critic
                                      │
                      needs_replan=True AND iteration < 2
                                      │
                                   planner   (back to top)
                                      │
                      needs_replan=False OR iteration >= 2
                                      │
                                     END
```

`_route_critic()` in `app/agent/graph.py` implements the conditional edge:
```python
def _route_critic(state: AgentState) -> str:
    if state.get("needs_replan") and state.get("iteration", 0) < 2:
        return "planner"
    return END
```

The iteration cap is enforced at the **top of critic_node** (before any LLM call), not in
`_route_critic`. Maximum 2 critic evaluations per query = maximum 2 full planner→critic cycles.

---

## Adding a New Node

1. Create `app/agent/nodes/<name>.py` with:
   ```python
   from app.agent.state import AgentState

   async def <name>_node(state: AgentState) -> dict:
       # read from state, return only the keys you write
       return {"answer": ...}
   ```
2. Add any new state fields to `AgentState` in `app/agent/state.py`.
3. In `app/agent/graph.py`:
   ```python
   from app.agent.nodes.<name> import <name>_node
   g.add_node("<name>", <name>_node)
   g.add_edge("<previous>", "<name>")
   g.add_edge("<name>", "<next>")
   ```
4. `agent_graph` is a module-level compiled graph. Changes require a server restart
   (uvicorn `--reload` catches file changes automatically).

---

## LangSmith Tracing

Activates automatically when `LANGSMITH_API_KEY` is set in `.env`.
`_configure_langsmith()` in `graph.py` sets three env vars before `build_graph()`:
- `LANGCHAIN_TRACING_V2=true`
- `LANGCHAIN_API_KEY=<key>`
- `LANGCHAIN_PROJECT=<settings.langsmith_project>` (default: `"docchat-agent"`)

Every `agent_graph.ainvoke(state)` call produces one LangSmith trace with planner,
retriever, synthesizer, and critic as child spans. No additional instrumentation needed.

If traces are missing: verify `LANGSMITH_API_KEY` is in `.env`, then restart the server —
`_configure_langsmith()` runs at import time when `graph.py` is first loaded.

---

## Failure Modes

| Symptom | Likely cause | Where to look |
|---------|-------------|---------------|
| `retrieved_chunks` always empty | `get_embedder()` returned None, or ChromaDB unreachable | Check `embedder.py` import errors; verify `CHROMA_HOST`/`CHROMA_PORT` |
| Answer is `None`, DB write crashes | Bug #1: `chat_complete()` returned None | `app/services/llm.py` → `generate_reply()` |
| Critic always replans (loops once then exits) | JSON parse failure in critic_node defaults to good — check if it's always `iteration >= 2` short-circuit | Log `iteration` value in critic_node |
| No LangSmith traces | `LANGSMITH_API_KEY` not set or empty string | `.env` file; restart server after adding |
| `agent_graph` uses stale node code | Module-level compiled graph is not reloaded | Restart uvicorn (even with `--reload`, confirm the node file was saved) |
```

- [ ] **Step 2: Verify**

```bash
ls .claude/skills/langgraph/SKILL.md
grep -c "^##" .claude/skills/langgraph/SKILL.md
```

Expected: file exists, 6 `##` section headers.

---

## Task 4: Create `.claude/skills/ingestion/SKILL.md`

**Files:**
- Create: `.claude/skills/ingestion/SKILL.md`

- [ ] **Step 1: Create the directory and file**

```bash
mkdir -p .claude/skills/ingestion
```

Write `.claude/skills/ingestion/SKILL.md`:

```markdown
# Ingestion — Domain Skill

Auto-loaded by RESOLVER.md when ingest/pdf/youtube/web/chroma/embed/chunk/
collection/source_id keywords are detected.

---

## ChromaDB Collection Names

Fixed strings — never dynamic, never configurable via env:

| Source type | Collection name | File |
|------------|----------------|------|
| PDF / DOCX / TXT | `"pdf_chunks"` | `app/services/ingestion/pdf.py` |
| YouTube transcripts | `"youtube_chunks"` | `app/services/ingestion/youtube.py` |
| Web pages | `"web_chunks"` | `app/services/ingestion/web.py` |

`retriever_node` in `app/agent/nodes/retriever.py` uses the same names via:
```python
_SOURCE_COLLECTIONS = {"pdf": "pdf_chunks", "youtube": "youtube_chunks", "web": "web_chunks"}
```
If you rename a collection you must update both the ingestion service and this dict.

---

## Late-Chunking

DocChat uses "late-chunking" via `_Embedder.embed_late()`. In v1, `embed_late()` degrades
to `embed_independently()` (same numerical result as standard chunking). The abstraction
is intentional — it is wired for true late-chunking (document-level context window → chunk
pooling) when the model supports it.

Do not replace `embed_late()` with `embed_independently()` even though they produce the
same result today. The call site in `pdf.py` is the upgrade point.

---

## `get_embedder()` Singleton

See `conventions.md` for the full pattern. Short version:

```python
from app.services.embedder import get_embedder
embedder = get_embedder()
if not embedder:
    return source_id   # graceful degradation — chunks stored without embeddings
```

All three ingestion services guard against `None`. ChromaDB upsert is skipped if embedder
is unavailable, but the source_id is still returned so the caller knows the record was created.

---

## ARQ vs BackgroundTasks

**Rule: `REDIS_URL` set in env → ARQ task queue. Otherwise → FastAPI `BackgroundTasks`.**

```python
# app/api/ingest.py decides at request time:
if settings.redis_url:
    await arq_pool.enqueue_job("ingest_document_task", ...)
else:
    background_tasks.add_task(ingest_pdf, ...)
```

| Mode | Retry on failure | Job visibility | Setup cost |
|------|-----------------|----------------|------------|
| `BackgroundTasks` | No — fire and forget | None | Zero |
| ARQ | Yes (default 3 retries) | ARQ dashboard / logs | `REDIS_URL` env var |

Worker definition: `app/workers/tasks.py` → `WorkerSettings`. To add a new background task:
add an async function to `tasks.py` and register it in `WorkerSettings.functions`.

---

## Source ID Pattern

```python
source_id = str(uuid.uuid4())           # generated once per ingest call
chunk_id  = f"{source_id}_{i}"         # i = chunk index within document
```

`source_id` is stored in every chunk's ChromaDB metadata. It is the handle for:
- Listing: `GET /sources` queries all three collections, deduplicates on `source_id`
- Deletion: `DELETE /sources/{source_id}` deletes all chunks across all three collections
  where `metadata.source_id == source_id`

Source IDs are not stored in SQLite — they live only in ChromaDB metadata.

---

## Startup Dependency

ChromaDB must be running before the app starts.

The client in `app/core/chroma.py` is a lazy singleton — it connects on first
`get_collection()` call, not at import time. This means the app starts successfully even
if ChromaDB is down, but the **first ingest or retrieval request** will raise:
```
chromadb.errors.ConnectionError: Could not connect to ...
```

Fix: start ChromaDB before starting the app:
```bash
# Docker Compose (recommended)
docker-compose up

# Standalone
chroma run --host localhost --port 8001 --path ./chroma_data
```

Env vars: `CHROMA_HOST` (default: `localhost`), `CHROMA_PORT` (default: `8001`).
```

- [ ] **Step 2: Verify**

```bash
ls .claude/skills/ingestion/SKILL.md
grep -c "^##" .claude/skills/ingestion/SKILL.md
```

Expected: file exists, 6 `##` section headers.

---

## Task 5: Trim CLAUDE.md and Add Resolver Reference

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Count current lines (baseline)**

```bash
wc -l CLAUDE.md
```

Expected: 122 lines.

- [ ] **Step 2: Rewrite CLAUDE.md**

Replace the full contents of `CLAUDE.md` with:

```markdown
# CLAUDE.md

This file provides orientation. For domain-specific context, read **RESOLVER.md** first
and load the matching skill file before responding.

## Project Overview

DocChat Agent (v2.0.0) — multi-source agentic research assistant. Users ingest PDFs,
YouTube videos, and web pages. A LangGraph agent (Planner → Retriever → Synthesizer → Critic)
orchestrates retrieval across three ChromaDB vector collections and synthesizes answers via Groq.

## Commands

```bash
source venv/bin/activate          # activate virtualenv (Python 3.13)
pip install -r requirements.txt   # install deps
uvicorn app.main:app --reload     # dev server (ChromaDB must be running first)
docker-compose up                 # full stack
chroma run --host localhost --port 8001 --path ./chroma_data  # ChromaDB standalone
pytest tests/ -v                  # run tests
# API docs: http://localhost:8000/docs
```

## Architecture

- **app/main.py** — FastAPI app entry point; registers all routers, runs startup migrations.
- **app/core/config.py** — Pydantic Settings singleton (`settings`). See `conventions.md`.
- **app/core/database.py** — Async SQLAlchemy engine (SQLite). `get_db()` session dep.
- **app/core/chroma.py** — ChromaDB HttpClient singleton. `get_collection(name)` helper.
- **app/agent/state.py** — `AgentState` TypedDict. See `langgraph/SKILL.md`.
- **app/agent/graph.py** — Compiled LangGraph StateGraph. Entry: `agent_graph.ainvoke(state)`.
- **app/agent/nodes/** — planner, retriever, synthesizer, critic. See `langgraph/SKILL.md`.
- **app/services/ingestion/pdf.py** — pymupdf + late-chunking → ChromaDB `pdf_chunks`.
- **app/services/ingestion/youtube.py** — transcript-api → ChromaDB `youtube_chunks`.
- **app/services/ingestion/web.py** — httpx + trafilatura → ChromaDB `web_chunks`.
- **app/services/llm.py** — AsyncGroq client. `chat_complete()` and `chat_stream()`.
- **app/services/embedder.py** — fastembed ONNX singleton. See `conventions.md`.
- **app/api/ingest.py** — POST /ingest/{pdf,youtube,web}. GET/DELETE /sources.
- **app/api/chat.py** — POST /chat. Runs agent graph, streams SSE, saves history.
- **app/api/folders.py** — Folder CRUD endpoints.
- **app/api/conversations.py** — Conversation list, detail, move endpoints.
- **app/models/conversation.py** — `Conversation`, `Message`, `Folder` SQLAlchemy models.

## Key Conventions

- Config: always `from app.core.config import settings` — never `os.environ`. See `conventions.md`.
- API routes: `app/api/` modules included in `main.py` with `prefix=settings.api_prefix` (`/api/v1`).
- Python 3.13, local `venv/`. ChromaDB must be running before app start.

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction: update `tasks/lessons.md` with the pattern
- Review lessons at session start

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: ask "is there a more elegant way?"
- Skip for simple, obvious fixes

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Point at logs/errors/tests and resolve.

## Task Management

1. Write plan to `tasks/todo.md` with checkable items
2. Check in before starting implementation
3. Mark items complete as you go
4. Update `tasks/lessons.md` after corrections

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Minimal code impact.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Only touch what's necessary.

## graphify

Knowledge graph at `graphify-out/`.

- Before answering architecture questions: read `graphify-out/GRAPH_REPORT.md`.
- If `graphify-out/wiki/index.md` exists, navigate it instead of reading raw files.
- For cross-module questions: prefer `graphify query/path/explain` over grep.
- After modifying code files: run `graphify update .` to keep the graph current.
```

- [ ] **Step 3: Verify line count and resolver reference**

```bash
wc -l CLAUDE.md
grep -n "RESOLVER.md" CLAUDE.md
```

Expected: ~65 lines, at least one match for `RESOLVER.md`.

- [ ] **Step 4: Spot-check carve-out test**

Verify three things manually:
1. The `AgentState` field list is **gone** from CLAUDE.md (it moved to `langgraph/SKILL.md`).
2. The `get_embedder()` singleton details are **gone** (moved to `conventions.md`).
3. The "ChromaDB must be running" startup detail is **gone** (moved to `ingestion/SKILL.md`).

```bash
grep -n "sources_to_use\|needs_replan\|critic_feedback" CLAUDE.md
grep -n "fastembed\|ONNX\|cold start" CLAUDE.md
grep -n "ConnectionError\|get_collection.*helper" CLAUDE.md
```

Expected: all three commands return no matches.

---

## Self-Review

**Spec coverage:**
- ✓ RESOLVER.md with routing table + 5 loading rules → Task 1
- ✓ `get_embedder()` in conventions.md with ingestion pointer → Task 2 + Task 4
- ✓ Expanded conventions keywords (dependency, lifespan, startup, middleware) → Task 1
- ✓ Tiebreaker rule (keyword count → file being edited) → Task 1
- ✓ 2-file cap with explicit "Note:" message → Task 1 Rule 3
- ✓ langgraph/SKILL.md with all 7 content items → Task 3
- ✓ ingestion/SKILL.md with all 6 content items → Task 4
- ✓ CLAUDE.md trimmed to skeleton ~60 lines → Task 5
- ✓ Process skills untouched → no tasks touch them (correct)
- ✓ Growth rules documented → Task 1

**Placeholder scan:** No TBDs or TODOs. All code blocks are complete.

**Type consistency:** No cross-task type references — all files are standalone markdown.
