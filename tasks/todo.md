# Active Task Checklist

## Fine-tuning readiness — SHIPPED 2026-08-19

The four blockers between here and a usable training corpus, plus two reporting
defects found while running the benchmark live.

- [x] `chat_complete` accepts `temperature`; omitted = provider default (unchanged)
- [x] Pin `temperature=0` at the classification call sites (critic, planner) only —
      the synthesizer keeps sampling; determinism matters for labels, not prose
- [x] Verify the live provider accepts it — **it does not.** gpt-5.6-luna 400s on
      temperature=0; we drop it, retry, and cache the refusal so the 400 is paid once
- [x] Prove the pin works where the model allows it — two Groq/qwen runs byte-identical
- [x] `AgentState.pending_rejection` — carries the rejected draft to the pass that
      knows the replacement
- [x] Sink writes ONE paired record (rejected + accepted + conversation_id +
      rejection_id). Unpaired halves are not worth collecting
- [x] Critic prompt: carve appropriate gap-admission out of "poor" — spec written,
      then revised after draft 1 cost 3/15 on the corruption set
- [x] `_report` must not print precision/F1 for an all-poor group — degenerate by
      construction, only recall carries information
- [x] Fix the cached-client/event-loop bug that made `pytest -m eval` unusable
- [x] Replace Groq's decommissioned default model (`llama-3.3-70b-versatile` 404s)
- [x] Tests for all of the above
- [x] Verify: `ruff check .` clean · `pytest -m "not eval" -q` → 153 passed
- [x] Verify: `pytest -m eval` → 8 passed (was 4 failed / 4 passed)
- [x] Verify: `python eval/benchmark.py` ×2 → edge 5/5, generated 15/15 both runs
- [x] Docs: HANDOFF, agent_memory, lessons, spec, test count

### Next

- [ ] Enable `CRITIC_REJECTION_LOG` and let pairs accumulate — nothing collected yet
- [ ] Spec giving `CRITIC_PROMPT` the retrieved context (unlocks `contradict_source`)
- [ ] Harder corruptions — the generated set is saturated at 15/15 and no longer
      discriminates

**Not rebuilding the e2e eval.** `eval/e2e_pipeline.py` already scores answer quality
with the critic loop on vs off (`run_compare`), real LLM calls, deterministic stubbed
retrieval. Earlier claim that it did not exist was wrong.

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

## LangSmith tracing + critic rejection sink — DONE 2026-08-15, NOT YET COMMITTED

Goal: make the LLM calls visible in traces (LangGraph only instruments nodes), and stop
throwing away drafts the critic rejects — replan overwrites them in place.

- [x] `_configure_langsmith()` uses modern `LANGSMITH_*` vars, not deprecated `LANGCHAIN_*`
- [x] `langsmith_tracing` flag so a noisy eval run can be silenced without pulling the key
- [x] `langsmith_endpoint` setting — EU keys 403 against the US host, looking like revocation
- [x] `@traceable` on `chat_complete` / `chat_stream` with provider/model metadata
- [x] `_join_stream` reducer so a trace shows the answer, not hundreds of token fragments
- [x] `tests/conftest.py` forces tracing off for the suite before `app` is imported
- [x] `critic_rejection_log` setting; blank disables the sink, opting in is deliberate
- [x] `_record_rejection()` writes JSONL and swallows every failure
- [x] Tests: 5 covering default-off, append, approved-skipped, field shape, unwritable sink
- [x] `langsmith` capped `<1.0.0` — code calls `reduce_fn` / `get_current_run_tree` directly
- [x] Verify: `ruff check .` clean
- [x] Verify: `pytest -m "not eval" -q` → 114 passed
- [ ] Commit as two separate commits (tracing; sink) — they are unrelated
- [ ] Decide `CriticCase.context`: write the corruption generator, or drop the field

---

## Corruption generator for the critic benchmark — SHIPPED 2026-08-16

Spec: `docs/superpowers/specs/2026-08-15-corruption-gen-design.md` (Option 1 approved)

- [x] Read `eval/cases.py` + `eval/benchmark.py`; confirm what the critic actually sees
- [x] Spec written, with the context finding and the revised transform set
- [x] Approval on Open Decision 1 — ship the context-free transforms
- [x] `eval/corruptions.py` — 4 pure transforms, each returning `None` when inapplicable
- [x] Cut `overclaim` and `drop_citation` too: both would inject mislabelled cases
- [x] `eval/cases.py` — `context` documented as provenance, not a critic input
- [x] `eval/benchmark.py` — generated cases scored separately, per-transform breakdown
- [x] `tests/test_corruptions.py` — 23 tests, weighted to what a transform must never do
- [x] Guard: no generated case reaches `CASES` (Layer B stays independent)
- [x] Guard: no transform ever returns its input unchanged (would poison the dataset)
- [x] Verify: `ruff check .` clean
- [x] Verify: `pytest -m "not eval" -q` → 137 passed; count updated in CLAUDE.md,
      HANDOFF.md, agent_memory.md
- [ ] **Not done:** run `python eval/benchmark.py` against a real key. The generated
      cases have only ever been scored by a development stub.

---

## Next Task — blocking model/provider A/B

The seam alone does not enable a provider comparison. `eval/benchmark.py` is not
reproducible: nothing sets `temperature`, and identical builds scored 3/5 then 2/5.

- [ ] Pin `temperature=0` for the classification nodes (critic, planner)
- [ ] Re-run the benchmark several times; confirm it is now stable
- [ ] Only then compare Groq vs OpenAI/Mistral

Leaving the synthesizer's temperature alone is probably right — determinism matters
for classification, less so for prose. Worth a deliberate decision, not a default.
