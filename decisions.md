# Decisions

Architectural decisions for DocChat v2. Each entry records what was decided, why, and what was explicitly ruled out. New decisions go at the bottom.

---

## 001 — Sources are global, not per-user

**Decision:** Ingested sources (PDFs, YouTube transcripts, web pages) are stored in Qdrant without user ownership. Any authenticated user can retrieve chunks from any source.

**Reasoning:** The retrieval pipeline (Qdrant + LangGraph agent) operates on the full corpus. Adding per-user filtering at the Qdrant query layer would require threading `user_id` through every ingestion service, every collection query in `retriever_node`, and the `AgentState`. The complexity cost is high and the benefit is low at current scale — DocChat is a single-tenant or trusted-team tool, not a multi-tenant SaaS.

**What was ruled out:** Storing `user_id` in Qdrant chunk payloads and filtering at query time. Not implemented because it would require changes to `ingest.py`, all three ingestion services (`pdf.py`, `youtube.py`, `web.py`), and `retriever_node` — touching the entire data path for a feature with no current user story.

**Revisit when:** A genuine multi-tenant requirement appears (different orgs, data isolation compliance, or a user explicitly requests "only search my documents").

---

## 002 — Auth uses JWT (not sessions)

**Decision:** Authentication uses short-lived JWT access tokens (30 min) plus long-lived refresh tokens (7 days, stored as SHA-256 hashes in SQLite). No server-side session store.

**Reasoning:** DocChat's API is stateless by design — the LangGraph agent, Qdrant queries, and SSE streaming all operate without session affinity. JWTs fit naturally: the server validates the token signature without a DB lookup on every request. Refresh tokens are hashed before storage so a DB breach does not expose usable tokens. Access tokens expire quickly to limit the blast radius of a leak.

**What was ruled out:** Server-side sessions (Redis or DB-backed). Ruled out because they require a session store, add a DB/cache lookup to every authenticated request, and introduce statefulness that complicates horizontal scaling. API key auth was also considered but ruled out — it has no expiry mechanism and no safe rotation path without user action.

**Revisit when:** OAuth2 social login (Google, GitHub) is needed — at that point, an OAuth2 library like `authlib` should replace the hand-rolled JWT layer rather than extending it.

---

## 003 — Decision 001's wording corrected: authentication is now actually required

**Decision:** Decision 001 said "any authenticated user can retrieve chunks from any source." That sentence described the intended policy, not the actual code: until this fix, `app/api/ingest.py` and `app/api/folders.py` had no `Depends(get_current_user)` on any route, so any caller, authenticated or not, could ingest, delete, or list sources, and create, rename, delete, or list folders. Every route in both files now requires authentication. Decision 001's policy (sources stay global across all authenticated users, not scoped per user) is unchanged and still correct; only the enforcement was missing.

**Reasoning:** This is a correction, not a new design decision. The gap was found during a codebase review and fixed directly: `Depends(get_current_user)` added to all 9 ingest/sources routes and all 4 folder routes, with tests asserting 401 on every one of them without a valid token.

**What was ruled out:** Nothing new. Decision 001's own reasoning for keeping sources global (not per-user) still holds and is not revisited here.

**Revisit when:** Not applicable — this entry exists to keep decisions.md honest about what the code actually does, not to flag a future change.
