# Implementation plan: LiteLLM backend and LoRA fine-tune (2026-11-02)

Design: `docs/superpowers/specs/2026-11-02-litellm-lora-finetune-design.md`. Checklist: `tasks/todo.md`.
Branch: `feat/litellm-lora-finetune`. Commits are small and separate (Part 1, data tooling, training code). No push.

## Part 1 steps

1. Check compatibility of `litellm` with the repo's requirements in a scratch venv; pin the exact version in
   `requirements-litellm.txt` (not in `requirements.lock`, so the production images do not change).
2. Add `llm_backend` to `app/core/config.py` (default `native`).
3. Write `app/services/llm_litellm.py`: lazy import, Router built from settings, `complete()` and `stream()` with the same
   contract as the native paths, fallback chain as designed, temperature rule, usage mapping, spans.
4. Delegate from `chat_complete()` / `chat_stream()` in `app/services/llm.py` only when the backend is `litellm`.
5. Tests in `tests/test_llm_litellm.py` (mocked, no network): completion, streaming, usage, retryable error, fallback to
   the second provider, `local` never a fallback target, temperature quirk, keys from settings, native default unchanged.
   Verify each guard by breaking it and watching the test fail.
6. `eval/llm_backend_parity.py`: same prompts through both backends against a local mock server; compare text, usage and
   span fields; measure import time, installed size and per-call overhead. Write findings in `docs/litellm-backend.md`.
7. Gates: `ruff check .` and `pytest -m "not eval" -q` green. Update HANDOFF.md, lessons. Stop and report.

## Part 2 steps (start only after the user approves a priced plan)

2a. `finetune/` data tooling and tests, `eval/prepare_heldout_v2.py`, source manifest. 2b. training script and smoke run.
2c. serve and evaluate three arms. 2d. `reports/finetune-vs-base-<date>.md`, README link.
