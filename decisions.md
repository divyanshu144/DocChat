# Decisions

Architectural decisions for DocChat v2. Each entry records what was decided, why, and what was explicitly ruled out. New decisions go at the bottom.

---

## 001 — Sources are global, not per-user

**Decision:** Ingested sources (PDFs, YouTube transcripts, web pages) are stored in ChromaDB without user ownership. Any authenticated user can retrieve chunks from any source.

**Reasoning:** The retrieval pipeline (ChromaDB + LangGraph agent) operates on the full corpus. Adding per-user filtering at the ChromaDB query layer would require threading `user_id` through every ingestion service, every collection query in `retriever_node`, and the `AgentState`. The complexity cost is high and the benefit is low at current scale — DocChat is a single-tenant or trusted-team tool, not a multi-tenant SaaS.

**What was ruled out:** Storing `user_id` in ChromaDB chunk metadata and filtering at query time. Not implemented because it would require changes to `ingest.py`, all three ingestion services (`pdf.py`, `youtube.py`, `web.py`), and `retriever_node` — touching the entire data path for a feature with no current user story.

**Revisit when:** A genuine multi-tenant requirement appears (different orgs, data isolation compliance, or a user explicitly requests "only search my documents").

---

## 002 — Auth uses JWT (not sessions)

**Decision:** Authentication uses short-lived JWT access tokens (30 min) plus long-lived refresh tokens (7 days, stored as SHA-256 hashes in SQLite). No server-side session store.

**Reasoning:** DocChat's API is stateless by design — the LangGraph agent, ChromaDB queries, and SSE streaming all operate without session affinity. JWTs fit naturally: the server validates the token signature without a DB lookup on every request. Refresh tokens are hashed before storage so a DB breach does not expose usable tokens. Access tokens expire quickly to limit the blast radius of a leak.

**What was ruled out:** Server-side sessions (Redis or DB-backed). Ruled out because they require a session store, add a DB/cache lookup to every authenticated request, and introduce statefulness that complicates horizontal scaling. API key auth was also considered but ruled out — it has no expiry mechanism and no safe rotation path without user action.

**Revisit when:** OAuth2 social login (Google, GitHub) is needed — at that point, an OAuth2 library like `authlib` should replace the hand-rolled JWT layer rather than extending it.
