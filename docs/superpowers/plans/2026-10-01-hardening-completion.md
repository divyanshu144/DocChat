# Hardening completion

Complete the remaining current checklist in tasks/todo.md without paid GPU runs.
Keep existing uncommitted work and unrelated Claude outputs intact.

1. Preserve original_query at all state entry points; retrieval alone uses rewrites.
   Fix body-only partial context truncation and warn on critic parse failures.
2. Batch CPU embeddings and synchronous Qdrant work in worker threads; prepare
   embeddings before deleting old source points; share source deletion with the API.
   Bound upload copies; await ordered job progress; recover interrupted jobs at startup.
   Rename the independent PDF embedding path and remove late-chunking claims.
3. Add bounded dependency health probes, configurable in-process rate limits,
   and user-wide refresh-token revocation on detected replay with atomic rotation.
4. Inspect the actual source_chunks corpus, label 20–30 evidence-backed retrieval
   queries, measure recall@k/MRR for dense, lexical, and CPU cross-encoder rankings.
   Keep measurements separate from production ranking and unit tests offline.
5. Write grounding-verdict and critic-context specs and evaluation plans, stopping
   before their behavioral implementations and paid evaluation runs.
6. Reconcile current documentation, archive historical TODO entries, shorten handoff.

Verification: meaningful offline tests for each behavior, full non-eval Python
suite and ruff, frontend test/build only if frontend changes. Live retrieval uses
existing local Qdrant and CPU models; no LLM calls or GPU pods. Record limitations.
