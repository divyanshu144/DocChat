# Agent prompt: LiteLLM provider layer + LoRA fine-tune, measured on the existing answer-quality harness

Paste this whole file as the first message of a fresh Claude Code session started in the `docchat` repo
(`~/Desktop/All Projects/docchat`, the full repo, not `docchat-submission`). Written 2026-11-02.

---

## Goal

Two linked pieces of work, each with a **measured, honestly reported** result:

1. **LiteLLM**: put LiteLLM behind the existing provider facade in `app/services/llm.py`, with provider fallbacks, and show behaviour is unchanged.
2. **LoRA fine-tune**: fine-tune a small open-weight model for grounded, cited document answers, serve it through vLLM behind the same facade, and compare it with its own base model and a hosted model using the answer-quality harness that already exists in `eval/`.

This is portfolio evidence for LLM-engineering roles (fine-tuning, multi-provider LLM workflows, evaluation). The only thing that has value is a result that is true. A negative or mixed result, written up properly, is a good outcome. A flattering result that does not hold up is a failure.

## Read first (before any code)

Follow this repo's own workflow rules in `CLAUDE.md`:

1. `CLAUDE.md`, `RESOLVER.md` (load the matching skill file for the domain), `HANDOFF.md`, `tasks/todo.md`, `tasks/lessons.md`, `tasks/agent_memory.md`.
2. Run `git status` and `git log -1`. If the working tree and `HANDOFF.md` disagree, the working tree wins. Report any uncommitted work before touching anything, and do not mix it into your commits. Work on a new branch.
3. Read these files in full: `app/services/llm.py`, `app/core/config.py`, the `eval/` scripts named below, and `reports/answer-quality-final-report-2026-10-06.md`.
4. Establish the baseline and show the output: `ruff check .` and `pytest -m "not eval" -q`. The recorded baseline is 841 passed with a PostgreSQL available (`TEST_DATABASE_URL`), or 834 passed and 7 skipped without. Any red you cause is a real regression.
5. This is non-trivial work, so use plan mode. Write a spec and plan under `docs/superpowers/specs/` and `docs/superpowers/plans/` (paired by date), put the checklist in `tasks/todo.md`, and **check in with the user before implementing**.

## Facts about the repo (verified 2026-11-02; re-verify before relying on them)

- `app/services/llm.py` (about 705 lines) is a Groq/Mistral/OpenAI/local provider facade exposing `chat_complete()` and `chat_stream()`. It has loop-owned clients, timing spans, a `usage_sink`, temperature handling (some models reject `temperature`, and the facade drops it and records that), retry classification (`_is_retryable_llm_error`), and a fallback path (`_can_fallback`, `_can_fallback_to_openai`).
- `app/core/config.py` has `llm_provider: Literal["groq","mistral","openai","local"]`, `fallback_llm_provider`, per-provider model names, and `local_base_url`, `local_chat_model`, `local_api_key`, `local_stream_completions`. **The `local` provider is deliberately excluded from the fallback chain** because a rented GPU may not be running. Preserve that rule.
- Defaults at the time of writing: `chat_model = "openai/gpt-oss-120b"` on Groq, `openai_chat_model = "gpt-5.6-luna"`, `mistral_chat_model = "mistral-small-latest"`. Verify them.
- The answer-quality harness lives in `eval/`: `prepare_quality_workload.py`, `generate_answer_samples.py`, `build_answer_review_pack.py`, `judge_answer_review_pack.py`, `judge_prompt.py`, `aggregate_judge_labels.py`, `audit_judge_labels.py`, `audit_answer_citations.py`, `build_spot_check_sheet.py`, `score_answer_review_pack.py`, `paired_format_comparison.py`, `positive_control.py`, `compare_judge_labels.py`. Serving and capacity scripts: `serving_load.py`, `inference_benchmark.py`, `quantization_compare.py`, `capacity_plan.py`, `gpu_sampler.py`. Retrieval: `retrieval_eval.py`, `retrieval_golden.json`.
- The existing report (`reports/answer-quality-final-report-2026-10-06.md`) is: 120 blinded answers from three serving formats (fp16, AWQ, GPTQ) of Qwen2.5-7B on an NVIDIA L40S, judged by `gpt-5.6-luna` with provider-default sampling, with an LLM audit correction layer, **LLM-assisted and not human-verified**, 72 development and 48 held-out rows, evidence from one working-time declaration PDF and one Wikipedia article on RAG. Read its limitations section and carry the same honesty into anything you write.

## Part 1: LiteLLM behind the facade

Constraints:

- Add LiteLLM as an **opt-in backend** (for example `llm_backend: Literal["native","litellm"] = "native"`). Do not delete the native paths in this task. Production default stays `native`.
- Keep the public signatures and behaviour of `chat_complete()` and `chat_stream()` unchanged: streaming shape, `usage_sink`, timing spans, the temperature-drop-and-record behaviour, the retry classification, and error types the rest of the app catches.
- Use a LiteLLM `Router` with explicit fallbacks that reproduce today's chain (primary, then the configured fallback), and keep `local` out of the fallback chain.
- Do not let LiteLLM read credentials from the environment on its own. Pass keys from `settings` only (the repo rule is `from app.core.config import settings`, never `os.environ`).
- Pin the LiteLLM version. Check the current docs (fallback and reliability pages) rather than relying on memory: behaviour around mock fallback flags and router settings has changed between versions.

Evidence required:

- Unit tests with mocked provider responses covering: normal completion, streaming, usage reporting, a retryable error, a fallback to the second provider, `local` never being a fallback target, and the temperature quirk.
- A parity check: run the same prompts through `native` and `litellm` and compare outputs and recorded usage. If live API credit is unavailable, say so and do not claim live parity. Do not weaken a test to make it pass.
- Report anything LiteLLM does **worse** or differently (latency overhead, extra dependency weight, streaming differences). A fair comparison matters more than a clean one.

## Part 2: LoRA fine-tune, measured

### 2a. Training data (the part most likely to be done wrong)

- Goal of the model: given retrieved chunks and a question, give a grounded answer with citations in DocChat's citation format, and **abstain correctly** when the chunks do not contain the answer. Match the real prompt format that `app/agent/nodes/synthesizer.py` uses, so training and serving agree.
- **Leakage is the main risk.** Build training data only from documents that are **not** the working-time declaration PDF or the Wikipedia RAG article used in the existing evaluation. Split by **document**, not by row. Write a decontamination check (exact and n-gram overlap against `reports/quality-review-pack*.jsonl`, the workloads in `eval/`, and `retrieval_golden.json`) and make it fail loudly. Record hashes of every training file and of the held-out evaluation inputs.
- Source documents must be legally usable (public domain or open licence). Record each source, its licence and its URL in a manifest. Do not use private or personal documents.
- If a model generates the training answers, check that provider's terms before using its outputs to train another model, and record the result. An open-weight teacher with a permissive licence is preferred. Do not use the same model family as the evaluation judge, to avoid self-preference bias.
- Filter generated examples: schema check, citation validity (every cited id exists in the supplied chunks), abstention examples included at a realistic rate, deduplication, and a manual spot-check of a sample that you describe in the report.

### 2b. Training

- Base model: the **same Qwen2.5-7B family already benchmarked**, so the comparison is like for like. Use QLoRA or LoRA with `transformers`, `peft` and `trl`. Fix the seed. Record the exact library versions, hyperparameters (rank, alpha, target modules, learning rate, epochs, batch size, max length), training and validation loss, wall-clock time and GPU cost.
- Keep weights and adapters **out of git** (add to `.gitignore`); store a path and a sha256 in the report instead.
- **Ask the user before any billable action.** State the GPU type, hourly price and the expected total before creating anything. Set a cost cap. Stop and shut resources down when the run ends or the cap is hit. Never print or log API keys.
- Run a tiny smoke run first (a few steps) to prove the pipeline works before committing to the full run.

### 2c. Serving and evaluation

- Serve the fine-tuned model with vLLM with LoRA adapters enabled, reachable through the existing `local` provider (and through LiteLLM if Part 1 is done).
- Use the existing harness unchanged wherever possible: same workload structure, same blinded review-pack builder, same judge prompt and judge model, same audit and citation-audit steps. Compare **base vs fine-tuned vs one hosted model** on the **held-out** split and keep development results separate.
- Add a human spot-check using the existing `build_spot_check_sheet.py` flow. The user does the human verdicts. Do not fill them in. Until they exist, label the results "LLM-assisted, not human-verified".
- Measure serving cost and speed with the existing scripts (`serving_load.py`, `capacity_plan.py`): throughput, p95 latency and the capacity under the same latency limit, so the trade-off against the hosted model is concrete.
- Report 95% intervals (Wilson, as in the existing report) and say plainly when differences are within noise. With about 48 held-out rows the intervals will be wide. Say that.

### 2d. Honest reporting

Write `reports/finetune-vs-base-<date>.md` in the style of the existing report: method, data and split, leakage checks and their results, judge details and known judge limitations, metrics table, serving cost and latency, limitations, and exactly what the numbers do **not** show. Include failure examples, not only wins. If the fine-tune is not better, say so and report what it costs and how fast it runs as the trade-off.

## Out of scope

- Voyage AI rerankers and MongoDB Atlas Vector Search (a later, separate task).
- Changing production configuration, deploying, or pushing to a remote without explicit approval.
- Committing model weights, datasets with licensing doubts, secrets, or `.env` values.
- Writing the user's CV or LinkedIn text. When results exist, report them and let the user decide what to claim.

## Rules of engagement

- Do not claim anything you did not measure. Do not describe the fine-tune as "better" unless held-out results support it beyond the stated intervals.
- Verify each guard or test by temporarily breaking the thing it protects and watching the test fail, as in the user's other projects (restore it immediately).
- Follow `CLAUDE.md`: simplicity first, minimal impact, root causes only. Update `tasks/lessons.md` after any correction, promote durable findings to `tasks/agent_memory.md`, and update `HANDOFF.md` at every checkpoint and before stopping.
- Small, separate commits (Part 1 and Part 2 separate, data tooling separate from training code). Do not push.

## Definition of done

1. `ruff check .` clean and `pytest -m "not eval" -q` fully green, with the output shown.
2. New logic has tests (LiteLLM seam, data validation, decontamination check, adapter-serving config).
3. The report exists with real numbers, intervals and limitations, and the README links to it.
4. `HANDOFF.md` reflects current state, including how to resume and what was **not** measured.
5. A short summary for the user: what was built, the headline numbers, what the numbers do not prove, cost spent, and what you would do next.
