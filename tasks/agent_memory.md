# Agent Memory

Durable structured reference. Unlike `lessons.md` (chronological log), this is the
curated current-truth view. **Locked decisions are honoured even if the code suggests
otherwise** — if the code disagrees with a locked decision, that's a bug to raise, not
a licence to change the decision.

---

## Architecture Decisions

| Decision | Status | Rationale |
|---|---|---|
| Three separate Qdrant collections (`pdf_chunks`, `youtube_chunks`, `web_chunks`) rather than one with a `type` filter | **Locked** | Different payload schemas per source; per-source retrieval tuning |
| Agent is a LangGraph `StateGraph`, not hand-rolled orchestration | **Locked** | Bounded critic-feedback retry loop needs explicit state machine |
| Config only via `from app.core.config import settings` — never `os.environ` | **Locked** | Single Pydantic Settings source of truth |
| Deterministic `uuid5` source IDs (content hash / canonical URL / video ID) | **Locked** (2026-07-02) | Re-ingesting the same input must be idempotent |
| Ruff gate covers `app/`, `tests/`, `eval/` — `scripts/` excluded | Provisional | `scripts/` has 22 outstanding findings; clean before removing the exclusion |
| `ruff format` NOT enforced | Provisional | Would reformat 44 files and destroy blame on an in-flight branch |
| `mcp` pinned `<2.0.0` | **Locked** (2026-07-28) | `mcp.server.fastmcp.FastMCP` was removed in 2.x; unpinning silently breaks the MCP server |

---

## Known Gotchas

- **The suite is fully green** — 73 passed, 0 failed. There are no known-failing tests,
  so any red is yours. (Was 45/4/12 before the 2026-07-28 venv rebuild.)
- **The critic cannot approve a correct "I can't answer from this context."** Its prompt
  defines good as "addresses the full query", so appropriate gap-admission scores poor.
  Measured by `eval/benchmark.py`: recall 1.00, precision 0.25–0.33 on edge cases — it
  over-fires, it does not miss. Fixing it is a prompt change needing its own spec.
- **`eval/benchmark.py` is NOT reproducible run-to-run.** Nothing sets `temperature`, so
  every node samples at the provider default. Back-to-back runs of the identical build
  scored 3/5 (P=0.33) then 2/5 (P=0.25). At N=5 one flip moves precision ~8 points, so
  **a single run cannot support an A/B comparison between models or providers.** Pin
  `temperature=0` for the classification nodes (critic, planner) before comparing
  anything, and average several runs.
- **`mcp` is capped below 2.0.** `app/mcp_server.py` uses `mcp.server.fastmcp.FastMCP`,
  removed in mcp 2.x. Lifting the cap requires rewriting that module.
- **Rebuild the venv before trusting `requirements.txt`.** A long-lived venv hid two
  broken requirements for months. See [lessons](lessons.md).
- **SQLAlchemy forward refs need `TYPE_CHECKING` imports.** `Mapped["User"]` resolves at
  runtime via the registry, but ruff F821 flags it without a `TYPE_CHECKING` import.
- **B008 fires on every FastAPI `Depends()`.** Configured away via
  `extend-immutable-calls` in `pyproject.toml` — do not "fix" the endpoints instead.
- **Ingestion is upsert-only.** Re-ingesting a *shorter* document leaves orphaned
  tail chunks; there is no version cleanup.
- **`git push --force` is blocked** by `~/.claude/hooks/pre-tool-use.sh`. The user runs
  force-pushes manually; don't try to route around the guard.

---

## Solved Problems

- **Follow-up questions lost context** → `conversation_history` was loaded in `chat.py`
  but never placed on `AgentState`. Fixed in `98b030e`; planner and synthesizer now
  format the last 10 messages into their prompts.
- **Refresh tokens didn't rotate** → `/auth/refresh` returned only an access token.
  Fixed in `98b030e`: old token revoked, new pair issued, frontend stores both.
- **Duplicate chunks on re-ingest** → `uuid4()` per ingest. Fixed in `98b030e` with
  `uuid5` derived from stable content identity.

---

## Useful Patterns

- **Verification baseline diffing:** before claiming a regression, `git stash` and re-run
  to establish what was already failing.
- **Spec → plan → implement:** specs and plans are paired by date in
  `docs/superpowers/{specs,plans}/`. Write both before code on any non-trivial feature.
- **Late chunking (PDF):** `_embed_chunks_late` embeds chunks with full-segment context
  and always returns exactly `len(raw_chunks)` entries — the `zip(..., strict=True)` in
  `ingest_pdf` documents that invariant.
