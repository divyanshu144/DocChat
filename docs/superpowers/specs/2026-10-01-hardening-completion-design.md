# Remaining hardening contracts

Companion implementation plan: `../plans/2026-10-01-hardening-completion.md`.

Keep retrieval rewrites in query and immutable user intent in original_query.
Synthesis, critique and rejection records use original_query with legacy-state
fallback. API, MCP and eval entry points initialize both. Planner never writes
original_query. Partial context truncation searches only in the body, never labels.

All ingestion embeddings use bounded independent CPU batches. Web and YouTube
prepare points in worker threads. Prepare embeddings before deleting the previous
source; shared source filtering/deletion/replacement serializes same-source writes
within a single process. Upserts wait for completion and propagate failures.
Delete/upsert is not transactional across batches. Shorter re-ingests have no tail
chunks after successful completion. No source is reported successfully ingested
when its embedder is unavailable or its content is empty.

Bound file-copy reads, reject beyond a positive configured size, and remove temp
files after failures. Async PDF progress callbacks are awaited serially before a
terminal status. Startup marks queued/running jobs as interrupted in the current
single-worker model. Multiple independent workers require shared job ownership.

Readiness probes run DB SELECT 1 and lightweight Qdrant collection listing in
parallel with bounded timeouts. Keep status/timestamp/version, add per-dependency
status, return 503 for either failure and never expose connection details.

Use a bounded per-process per-IP sliding-window limiter on login/signup/chat.
Read limits from settings and return 429 with Retry-After. Do not trust forwarded
headers within the limiter. Fail closed when the bounded key store is full.

Refresh rotates through an atomic conditional update; PostgreSQL also locks the
user row. Known revoked-token replay revokes all refresh sessions for that user
and commits before returning 401. Unknown/invalid tokens do not revoke legitimate
sessions. Existing access tokens retain their normal expiry.

Retrieval evaluation labels chunk IDs and their source/page metadata from the real
corpus. Compare exact dense cosine, the production lexical score and an isolated
CPU cross-encoder on identical candidates. Report recall@1/3/5 and MRR at ranking
depth 12, with per-query results, corpus fingerprint and limitations. Do not deploy
the experimental ranker from this measurement alone.
