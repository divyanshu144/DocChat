# Active Task Checklist

Written before implementation, checked off as each item completes — one at a time,
not batched. Clear this file when a task ships; history lives in git, not here.

---

## LLM provider + chat UX hardening — SHIPPED 2026-07-29

Goal: make the document Q&A experience usable under live provider failures, show
progress while work runs, preserve chat continuity, and document the current state for
the next agent session.

- [x] `llm_provider` setting supports Groq, OpenAI, and Mistral
- [x] Per-provider model settings so switching provider is one variable, not two
- [x] `_build_client` with lazy SDK imports — unused provider's package never loads
- [x] Client cache keyed by provider so flipping at runtime rebuilds
- [x] `_text()` normaliser — Mistral content can be typed chunks, not just `str`
- [x] Groq retry/fallback path can use OpenAI on retryable failures
- [x] OpenAI direct provider path uses `OPENAI_CHAT_MODEL` + `OPENAI_API_KEY`
- [x] SSE chat status events show planner/retriever/synthesizer/grounding/critic progress
- [x] Backend refuses to persist blank assistant messages
- [x] Grounding verifier meta-failure preserves the original draft
- [x] PDF ingest jobs expose progress/status instead of blocking silently
- [x] Chat UI preserves prior messages, scrolls correctly, and skips empty bubbles
- [x] Mistral coded against the *real* SDK surface (inspected mistralai 2.8.0), not a guess
- [x] Tests: dispatch, model selection, cache rebuild, unknown provider, normalisation
- [x] Verify: `ruff check .` clean
- [x] Verify: `pytest -m "not eval" -q` → 109 passed
- [x] Verify: frontend build passes from `frontend/`

---

## Next Task — blocking model/provider A/B

The seam alone does not enable a provider comparison. `eval/benchmark.py` is not
reproducible: nothing sets `temperature`, and identical builds scored 3/5 then 2/5.

- [ ] Pin `temperature=0` for the classification nodes (critic, planner)
- [ ] Re-run the benchmark several times; confirm it is now stable
- [ ] Only then compare Groq vs OpenAI/Mistral

Leaving the synthesizer's temperature alone is probably right — determinism matters
for classification, less so for prose. Worth a deliberate decision, not a default.
