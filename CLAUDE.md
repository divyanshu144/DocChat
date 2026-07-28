# CLAUDE.md

This file provides orientation. For domain-specific context, read **RESOLVER.md** first
and load the matching skill file before responding.

## Project Overview

DocChat Agent (v2.0.0) — multi-source agentic research assistant. Users ingest PDFs,
YouTube videos, and web pages. A LangGraph agent (Planner → Retriever → Synthesizer →
Grounding → Critic) orchestrates retrieval across three Qdrant vector collections and
synthesizes cited answers via Groq.

## Commands

```bash
source venv/bin/activate          # Python 3.13 virtualenv
pip install -r requirements.txt   # install deps
ruff check .                      # lint  (must be clean)
pytest -m "not eval" -q           # tests  (must be fully green)
pytest -m eval -v                 # critic regression, hits the real Groq API
uvicorn app.main:app --reload     # dev server (needs Qdrant + PostgreSQL)
docker compose up --build         # full stack
# UI + API docs: http://localhost:8081  /  http://localhost:8081/docs
```

**Verification baseline (2026-07-28):** both gates are green — `ruff check .` clean,
`pytest -m "not eval"` **61 passed, 0 failed**. There are no known-failing tests, so
*any* red is a real regression you introduced. Do not rationalise a failure as
pre-existing without diffing against a stash.

## Architecture

- **app/main.py** — FastAPI app entry point; registers all routers, runs startup migrations.
- **app/core/config.py** — Pydantic Settings singleton (`settings`). See `conventions.md`.
- **app/core/database.py** — Async SQLAlchemy engine (PostgreSQL by default). `get_db()` session dep.
- **app/core/qdrant.py** — QdrantClient singleton. `get_qdrant_collection(name)` helper.
- **app/agent/state.py** — `AgentState` TypedDict. See `langgraph/SKILL.md`.
- **app/agent/graph.py** — Compiled LangGraph StateGraph. Entry: `agent_graph.ainvoke(state)`.
- **app/agent/nodes/** — planner, retriever, synthesizer, grounding, critic. See `langgraph/SKILL.md`.
- **app/services/ingestion/pdf.py** — pymupdf + late-chunking → Qdrant `pdf_chunks`.
- **app/services/ingestion/youtube.py** — transcript-api → Qdrant `youtube_chunks`.
- **app/services/ingestion/web.py** — httpx + trafilatura → Qdrant `web_chunks`.
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
- Python 3.13, local `venv/`. Use Docker Compose for Qdrant and PostgreSQL during local work.

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction or non-obvious discovery: append to `tasks/lessons.md`
  (what broke / root cause / what to do next time)
- Promote durable findings into `tasks/agent_memory.md`
- Review both at session start

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Run the Definition of Done checks below and **show the output**
- "It should work" is not verification

### 5. Demand Elegance (Balanced)
- For non-trivial changes: ask "is there a more elegant way?"
- Skip for simple, obvious fixes

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Point at logs/errors/tests and resolve.

## Session Files

Read these at the START of every session, then run `git status` + `git log -1` and
reconcile. **If they disagree, the working tree is authoritative** — fix the doc.

| File | Purpose | Update when |
|---|---|---|
| `HANDOFF.md` | Cold-start resume point: Current State, Next Action, In-Flight files, Open Questions, Verification Baseline | Task complete · milestone · blocker · user signals stop · context ~70% |
| `tasks/todo.md` | Current task as a checklist | Before implementing; tick items one at a time, never batched |
| `tasks/lessons.md` | Chronological log of corrections and discoveries | After ANY correction or non-obvious discovery |
| `tasks/agent_memory.md` | Curated reference: Architecture Decisions, Known Gotchas, Solved Problems, Useful Patterns | When a lesson becomes durable, or a decision is locked |
| `docs/superpowers/specs/` · `docs/superpowers/plans/` | Written specs and implementation plans, paired by date | Before writing code on any non-trivial feature |

`HANDOFF.md` going stale is this project's known failure mode — it sat ~2 months out of
date while a whole feature shipped. Treat updating it as part of the task, not cleanup.

## Task Management

1. Write plan to `tasks/todo.md` with checkable items
2. Check in before starting implementation
3. Mark items complete as you go — one at a time
4. Update `tasks/lessons.md` after corrections
5. Update `HANDOFF.md` before you stop

## Definition of Done

A task is not complete until **all** of these hold:

1. `ruff check .` passes clean
2. `pytest -m "not eval" -q` is fully green — 61 passed, 0 failed
3. New logic has tests
4. `HANDOFF.md` reflects current state

Run them and show the output. Do not assert.

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Minimal code impact.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Only touch what's necessary.
