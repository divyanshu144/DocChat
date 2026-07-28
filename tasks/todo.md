# Active Task Checklist

Written before implementation, checked off as each item completes — one at a time,
not batched. Clear this file when a task ships; history lives in git, not here.

---

## Critic Accuracy Benchmark (Layer A) — SHIPPED 2026-07-28

Spec: `docs/superpowers/specs/2026-05-28-critic-benchmark-design.md` (approved)
Plan: spec was implementation-ready — functions, metrics and report format all
specified, so no separate plan file was written.

- [x] Add `BENCHMARK_CASES: list[CriticCase]` to `eval/cases.py` (5 cases, below `CASES`)
- [x] Create `eval/benchmark.py` — `run_case()`, `_compute_metrics()`, `main()`
- [x] Metrics: positive class is `"poor"`; N/A on zero denominators
- [x] Report matches the spec's format, `[FAIL]` lines carry critic feedback
- [x] Exits 0 regardless of score — verified exit code 0
- [x] Verify: `ruff check .` clean
- [x] Verify: `pytest -m "not eval" -q` → 73 passed (61 + 12 new metric tests)
- [x] Verify: ran `python eval/benchmark.py` against real Groq — 3/5, P=0.33 R=1.00 F1=0.50
- [x] Update `HANDOFF.md` — Layer A moved out of Open Work

**Deviation from spec:** added `tests/test_benchmark_metrics.py` (not in the spec).
The DoD requires new logic to have tests and `_compute_metrics` is pure, so it is
cheap to cover and would otherwise only ever be exercised by a paid LLM run.

---

## Current Task

_None active._
