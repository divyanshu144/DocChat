# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DocChat Agent is a multi-source agentic research assistant (v2.0.0). Users ingest PDFs, YouTube videos, and web pages. A LangGraph agent (Planner → Retriever → Synthesizer → Critic) orchestrates retrieval across three ChromaDB vector collections and synthesizes answers via Groq. All LLM traces visible in LangSmith.

## Commands

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the dev server (requires ChromaDB running — see Docker below)
uvicorn app.main:app --reload

# Start full stack with Docker Compose
docker-compose up

# Run ChromaDB locally (without Docker)
pip install chromadb
chroma run --host localhost --port 8001 --path ./chroma_data

# Run tests
pytest tests/ -v

# API docs
http://localhost:8000/docs
```

## Architecture

- **app/main.py** — FastAPI app, registers health/ingest/chat routers, SQLite table creation on startup.
- **app/core/config.py** — Pydantic Settings singleton. Extended with ChromaDB, LangSmith, YouTube settings.
- **app/core/database.py** — Async SQLAlchemy engine (SQLite). Stores conversation history only.
- **app/core/chroma.py** — ChromaDB HttpClient singleton + `get_collection(name)` helper.
- **app/agent/state.py** — `AgentState` TypedDict (query, sources_to_use, retrieved_chunks, answer, critic_feedback, needs_replan, iteration).
- **app/agent/graph.py** — Compiled LangGraph StateGraph. Entry point: `agent_graph.ainvoke(state)`.
- **app/agent/nodes/** — Four nodes: `planner` (source selection), `retriever` (ChromaDB queries), `synthesizer` (Groq answer), `critic` (quality gate with replan loop).
- **app/services/ingestion/pdf.py** — pymupdf + late-chunking embedder → ChromaDB `pdf_chunks`.
- **app/services/ingestion/youtube.py** — youtube-transcript-api + pytube → ChromaDB `youtube_chunks`.
- **app/services/ingestion/web.py** — httpx + trafilatura → ChromaDB `web_chunks`.
- **app/services/llm.py** — AsyncGroq client. `chat_complete()` and `chat_stream()`.
- **app/services/embedder.py** — fastembed BAAI/bge-small-en-v1.5 ONNX wrapper. Used by all ingestion services and the retriever.
- **app/api/ingest.py** — POST /ingest/pdf, /ingest/youtube, /ingest/web. GET/DELETE /sources.
- **app/api/chat.py** — POST /chat. Runs agent, saves history to SQLite, streams SSE answer.
- **app/models/conversation.py** — `Conversation` + `Message` SQLAlchemy models (conversation history).

## Key Conventions

- Configuration is centralized via `app.core.config.settings` — always use this rather than reading env vars directly.
- API routes live in `app/api/` as separate router modules, included in `main.py` with `settings.api_prefix` (`/api/v1`).
- Python 3.13 with a local `venv/` virtual environment.
- ChromaDB must be running before starting the app (`CHROMA_HOST` + `CHROMA_PORT` env vars).
- LangSmith tracing activates automatically when `LANGSMITH_API_KEY` is set.

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: Pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
