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
source venv/bin/activate          # activate virtualenv (Python 3.13)
pip install -r requirements.txt   # install deps
uvicorn app.main:app --reload     # dev server (Qdrant/PostgreSQL must be running)
docker-compose up                 # full stack: app + Qdrant + PostgreSQL
pytest tests/ -v                  # run tests
# API docs: http://localhost:8000/docs
```

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
