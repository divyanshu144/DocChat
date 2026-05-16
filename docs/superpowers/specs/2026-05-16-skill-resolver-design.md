# Skill Resolver — Design Spec
_DocChat · 2026-05-16_

## Goal

Replace the monolithic `CLAUDE.md` with a lightweight skeleton + a keyword-driven resolver that auto-loads domain-specific skill files. Agents get precise, relevant context instead of scanning 122 lines of mixed concerns. CLAUDE.md shrinks to ~60 lines of orientation. Two new domain skills and one conventions file carry the depth.

---

## Mental Model

**Two kinds of skills, two trigger mechanisms:**

| Kind | Examples | Triggered by |
|------|----------|--------------|
| Process skills | `fde-plan`, `fde-review`, `debug-playbook`, `api-conventions`, `pr-checklist` | User (slash command / explicit invocation) |
| Domain skills | `langgraph`, `ingestion`, `conventions` | Agent (RESOLVER.md keyword match at response time) |

Process skills are things *you* reach for. Domain skills are things *Claude* reaches for. They don't mix.

**The carve-out test** (apply to every line when editing CLAUDE.md):
> Would removing this make an agent working in a **different** domain worse off? If no → it belongs in the domain skill file, not CLAUDE.md.

---

## File Structure

```
docchat/
├── CLAUDE.md                        ← trimmed skeleton (~60 lines)
├── RESOLVER.md                      ← new: keyword routing table
└── .claude/skills/
    │
    │   # Domain skills (agent-loaded)
    ├── langgraph/
    │   └── SKILL.md                 ← new
    ├── ingestion/
    │   └── SKILL.md                 ← new
    ├── conventions.md               ← new (single file; promote to folder if >200 lines)
    │
    │   # Process skills (user-invoked, untouched)
    ├── api-conventions/
    ├── debug-playbook/
    ├── fde-plan/
    ├── fde-review/
    └── pr-checklist/
```

---

## RESOLVER.md

Lives at project root alongside CLAUDE.md. Claude reads it at the start of every response and loads matching skill files before answering.

### Two-Tier Model

Skills in this resolver operate at two different tiers:

- **Near-default (conventions.md)**: Loaded for any implementation, debugging, or code-change task. Not keyword-triggered — it's the baseline for any task where wrong conventions could silently introduce bugs. The only case to skip it: purely read-only tasks (explaining, reviewing, answering architecture questions).
- **Conditional (langgraph, ingestion)**: Loaded only when the task touches their specific domain. Keyword-triggered. These carry depth that would be noise on unrelated tasks.

This distinction is intentional. A keyword list for conventions.md (`settings`, `config`, `async`, ...) would match ~90% of messages anyway and would still miss cases where the pattern is relevant but no keyword appears. Better to be honest: it's a near-default, not a triggered skill.

### Routing Table

| Keywords | Skill file | Load when |
|----------|-----------|-----------|
| `agent` `graph` `node` `critic` `planner` `retriever` `synthesizer` `AgentState` `replan` `LangGraph` | `.claude/skills/langgraph/SKILL.md` | Any task touching the agent pipeline |
| `ingest` `pdf` `youtube` `web` `chroma` `embed` `chunk` `collection` `source_id` | `.claude/skills/ingestion/SKILL.md` | Any task touching data ingestion or ChromaDB |
| Any implementation or debugging task | `.claude/skills/conventions.md` | Default: load unless task is clearly read-only (explaining, reviewing, answering questions) |

### Loading Rules

1. **`conventions.md` is near-default** — load it for any implementation, debugging, or code-change task. Skip only when the task is purely read-only.
2. **Domain skills are conditional** — load only when the task touches their domain (keyword match or file context).
3. **Load at most 2 files per response** — one domain skill + `conventions.md`. If two domain skills both match, load the primary (most keyword matches; tie → file being edited) and note the other.
4. **When the 2-file cap drops a relevant domain skill**, state it explicitly at the top of the response: "Note: this task also touches [domain] — invoke `/[skill]` if you need that context." Never operate with silently incomplete context.
5. **Process skills are never auto-loaded** — `fde-plan`, `fde-review`, `api-conventions`, `debug-playbook`, `pr-checklist` are user-invoked only.

---

## CLAUDE.md Changes

### What stays

- Project overview (2–3 sentences, no module-by-module breakdown)
- Commands block (unchanged)
- Architecture list: **one line per module**, file path + single-sentence purpose only
- Reference line pointing to RESOLVER.md
- Workflow orchestration rules (Plan Mode, Subagent Strategy, etc.)
- Task management workflow
- Core principles
- Graphify rules

### What moves out

| Content | Destination |
|---------|-------------|
| AgentState field meanings, node contracts, critic loop mechanics | `langgraph/SKILL.md` |
| ChromaDB collection conventions, chunking rationale, ARQ decision rule | `ingestion/SKILL.md` |
| `get_embedder()` singleton gotchas (cold start, ONNX, reinitialization) | `conventions.md` (ingestion skill gets a one-liner pointer) |
| `settings` singleton pattern, `get_db()` session pattern, async invariants | `conventions.md` |

**Target:** ~60 lines. Every line passes the carve-out test.

---

## Domain Skill Contents

### `langgraph/SKILL.md`

- `AgentState` TypedDict: each field, its type, what it means, who writes it
- Node contracts: what each node (planner, retriever, synthesizer, critic) expects as input and guarantees as output
- Critic replan loop: when it triggers, max iteration cap, what happens when the cap is hit
- `_route_critic()` logic: the conditional edge, what signals cause replan vs exit
- How to add a new node safely (state fields to add, edge wiring, checkpoint impact)
- LangSmith tracing: what gets traced automatically, how to add custom metadata
- Failure modes: what breaks silently vs loudly, where to look first

### `ingestion/SKILL.md`

- ChromaDB collection names: `pdf_chunks`, `youtube_chunks`, `web_chunks` — fixed, never dynamic
- Late-chunking vs regular chunking: what it is, why DocChat uses it, when it matters
- `get_embedder()`: one-liner pointer to `conventions.md` for the singleton pattern
- ARQ vs BackgroundTasks: rule is `REDIS_URL present → ARQ`, otherwise `BackgroundTasks`; implications for task retries and observability
- Source ID pattern: how it's generated, where it's stored, how deletion works
- Startup dependency: ChromaDB must be running before app starts (`CHROMA_HOST` + `CHROMA_PORT`); the error it produces if not

### `conventions.md`

- **`settings` singleton**: always `from app.core.config import settings`. Never `os.environ` directly. Why: pydantic validation, `.env` loading, test overridability.
- **`get_db()` async session**: FastAPI dependency injection pattern. Never construct `AsyncSession` directly outside this. Why: connection pool hygiene.
- **`get_embedder()` singleton**: fastembed BAAI/bge-small-en-v1.5 ONNX. ~2s cold start on first call. Do not reinitialize — it is not designed to be called more than once per process. Used by both ingestion services and `retriever.py`.
- **Async invariants**: all I/O is async. Never call blocking code in an async path (the known violation is `_chunk_segments` — see audit). Use `asyncio.to_thread()` for CPU-bound work.
- **API prefix**: always `settings.api_prefix` (`/api/v1`). Never hardcode the string. Router modules declare routes without the prefix; `main.py` adds it at include time.

---

## Growth Rules

- **Add a keyword row** to RESOLVER.md when a new domain skill is created. Run a quick grep to check for false-positive matches before committing.
- **Promote `conventions.md` to `conventions/`** if it exceeds ~200 lines or a third domain with meaningfully different convention needs appears.
- **Duplication policy**: a rule that appears in both a process skill and `conventions.md` is acceptable if the trigger mechanisms differ. Do not merge files to eliminate the duplication.

---

## Out of Scope

- Changes to existing process skills (`fde-plan`, `fde-review`, etc.)
- Automating resolver invocation via hooks (future: could wire `PreToolUse` hook to inject skill content, but manual reading is sufficient for now)
- A `check-resolvable` CLI (useful at 10+ skills; overkill at 3)
