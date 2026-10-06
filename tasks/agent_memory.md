# Agent Memory

Durable structured reference. Unlike `lessons.md` (chronological log), this is the
curated current-truth view. **Locked decisions are honoured even if the code suggests
otherwise** — if the code disagrees with a locked decision, that's a bug to raise, not
a licence to change the decision.

---

## Architecture Decisions

| Decision | Status | Rationale |
|---|---|---|
| One normalized `source_chunks` collection with `source_type` / `source_id` payload filters | **Current (supersedes the former three-collection decision)** | Shared storage/retrieval for future source types; legacy collections only listed/deleted |
| Agent is a LangGraph `StateGraph`, not hand-rolled orchestration | **Locked** | Bounded critic-feedback retry loop needs explicit state machine |
| Config only via `from app.core.config import settings` — never `os.environ` | **Locked** | Single Pydantic Settings source of truth |
| Deterministic `uuid5` source IDs (content hash / canonical URL / video ID) | **Locked** (2026-07-02) | Re-ingesting the same input must be idempotent |
| OpenAI is a first-class LLM provider | **Locked** (2026-07-29) | `LLM_PROVIDER=openai` uses `OPENAI_CHAT_MODEL` + `OPENAI_API_KEY`; Groq may fall back to OpenAI only for retryable failures |
| Never persist blank assistant answers | **Locked** (2026-07-29) | Chat must preserve the last non-empty graph answer or emit a usable fallback message |
| Ruff gate covers `app/`, `tests/`, `eval/` — `scripts/` excluded | Provisional | `scripts/` has 22 outstanding findings; clean before removing the exclusion |
| `ruff format` NOT enforced | Provisional | Would reformat 44 files and destroy blame on an in-flight branch |
| `mcp` pinned `<2.0.0` | **Locked** (2026-07-28) | `mcp.server.fastmcp.FastMCP` was removed in 2.x; unpinning silently breaks the MCP server |
| Critic judges gap-admission by DISCLOSURE, in two ordered steps | **Locked** (2026-08-19) | Step 1 (self-contradiction/vague/off-topic) is poor regardless of honesty; only step 2 excuses a *disclosed* gap. A single-paragraph version leaked the carve-out into corruptions and cost 3/15 |
| Classification nodes pinned to `temperature=0`, synthesizer left sampling | **Locked** (2026-08-19) | A verdict is a label and must not move between runs; prose gains nothing from determinism |
| Rejection sink writes complete (rejected, accepted) pairs only | **Locked** (2026-08-19) | A lone rejection is half a training example — unusable for SFT or preference training |

---

## Known Gotchas

- **Current offline baseline (2026-10-05):** 428 passed, 8 live evals deselected;
  ruff clean. Historical counts below describe their original sessions.
- **A model can silently refuse `temperature`.** `gpt-5.6-luna` 400s on
  `temperature=0` ("Only the default (1) value is supported"); `app/services/llm.py`
  drops the parameter and retries so the request still succeeds, caching the refusal per
  model so the 400 is paid once. Consequence: **the classification pin is a no-op on that
  model and verdicts still move between runs.** Verified deterministic on
  `LLM_PROVIDER=groq` + `qwen/qwen3.6-27b` (two runs byte-identical across 20 verdicts).
  Grep the logs for `openai_rejected_temperature_retrying_without` before trusting a delta.
- **Groq model IDs go away.** `llama-3.3-70b-versatile` was the default and is
  decommissioned — the entire Groq path 404'd on defaults. Now `openai/gpt-oss-120b`.
  Check `GET /models` before setting `CHAT_MODEL`. Also: `qwen/qwen3.6-27b` rates
  *everything* good (recall 0.00) and is unusable as a critic.
- **The cached LLM client is bound to one event loop.** `app.services.llm` now owns
  clients by event loop and connection configuration (2026-10-04). API/MCP shutdown
  and benchmark teardown close all clients on that loop. Standalone scripts must call
  `close_llm_clients()` in finally. Tests isolate their mocked registries.
- **`mcp` is capped below 2.0.** `app/mcp_server.py` uses `mcp.server.fastmcp.FastMCP`,
  removed in mcp 2.x. Lifting the cap requires rewriting that module.
- **Rebuild the venv before trusting `requirements.txt`.** A long-lived venv hid two
  broken requirements for months. See [lessons](lessons.md).
- **SQLAlchemy forward refs need `TYPE_CHECKING` imports.** `Mapped["User"]` resolves at
  runtime via the registry, but ruff F821 flags it without a `TYPE_CHECKING` import.
- **B008 fires on every FastAPI `Depends()`.** Configured away via
  `extend-immutable-calls` in `pyproject.toml` — do not "fix" the endpoints instead.
- **Ingestion replaces same-source points.** Embeddings are prepared first, then
  delete-by-source_id and batched upsert run in a worker. This is not transactional;
  retry an indexing failure. Single-process source locks do not coordinate multiple workers.
- **Single-worker job recovery.** Startup marks queued/running jobs as interrupted.
  Move to a shared durable queue before running independent app workers.
- **Rate limits are per-process/IP.** Auth and chat return 429 with Retry-After;
  multi-worker deployments need a shared limiter. Forwarded headers are not trusted.
- **Refresh replay revokes all refresh sessions for that user.** Access tokens
  remain valid until their normal expiry; frontend refresh requests are coalesced.
- **Docker Compose `restart` does not reload `.env`.** Use
  `docker compose up -d --force-recreate app` after changing provider/env settings.
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
- **Groq 429 caused visible stream failures** → `app/services/llm.py` now supports
  OpenAI as a provider and can fall back from Groq to OpenAI on retryable failures.
- **PDF ingest blocked silently** → `POST /ingest/pdf/jobs` and
  `GET /ingest/jobs/{job_id}` expose progress; the source drawer polls job status.
- **Latest chat turn hid older content / blank answers appeared** → frontend keeps the
  streamed transcript locally, backend orders messages by `created_at,id`, and chat
  refuses to persist empty assistant messages.
- **Grounding verifier returned "I don't have an answer to clean"** → guarded in
  `app/agent/nodes/grounding.py`; the original draft is kept on verifier meta-failure.

---

## Useful Patterns

- **Verification baseline diffing:** before claiming a regression, `git stash` and re-run
  to establish what was already failing.
- **Spec → plan → implement:** specs and plans are paired by date in
  `docs/superpowers/{specs,plans}/`. Write both before code on any non-trivial feature.
- **Independent chunk embedding:** PDF, web and YouTube use bounded fastembed
  batches; no segment-level token pooling or true late chunking is implemented.


## Serving platform checkpoints (2026-10-05)

- Phase 1 adapter/telemetry and Phase 2 metrics/sustained harness are implemented and
  tested offline. GPU acceptance, held-out quality evaluation and capacity planning
  are not complete. See current HANDOFF.md before inferring experimental progress.
- `/api/v1/metrics` is single-process, optional bearer protection. Scrape private
  endpoints; no identity/content metric labels. vLLM metrics remain a separate job.
- `eval.inference_benchmark sustained` writes schema v2 to a fresh directory. Never
  mix it with historical burst JSONL. API benchmarks create conversations and require
  an isolated account/deployment with suitable token lifetime and explicit rate limits.
