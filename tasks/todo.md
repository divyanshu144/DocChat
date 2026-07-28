# Active Task Checklist

Written before implementation, checked off as each item completes — one at a time,
not batched. Clear this file when a task ships; history lives in git, not here.

---

## LLM provider seam — SHIPPED 2026-07-29

Step 1 of the Mistral fine-tuning track. Goal is A/B-ability, not migration:
Groq stays the production default.

- [x] `llm_provider` setting (`Literal["groq","mistral"]`, defaults to groq)
- [x] Per-provider model settings so switching provider is one variable, not two
- [x] `_build_client` with lazy SDK imports — unused provider's package never loads
- [x] Client cache keyed by provider so flipping at runtime rebuilds
- [x] `_text()` normaliser — Mistral content can be typed chunks, not just `str`
- [x] Mistral coded against the *real* SDK surface (inspected mistralai 2.8.0), not a guess
- [x] Tests: dispatch, model selection, cache rebuild, unknown provider, normalisation
- [x] Verify: `ruff check .` clean
- [x] Verify: `pytest -m "not eval" -q` → 87 passed (73 + 14 new)
- [x] Verify: both clients construct against real SDKs; live Groq run through new seam

---

## Next Task — blocking the A/B

The seam alone does not enable a provider comparison. `eval/benchmark.py` is not
reproducible: nothing sets `temperature`, and identical builds scored 3/5 then 2/5.

- [ ] Pin `temperature=0` for the classification nodes (critic, planner)
- [ ] Re-run the benchmark several times; confirm it is now stable
- [ ] Only then compare Groq vs Mistral

Leaving the synthesizer's temperature alone is probably right — determinism matters
for classification, less so for prose. Worth a deliberate decision, not a default.
