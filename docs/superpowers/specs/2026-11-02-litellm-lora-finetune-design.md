# LiteLLM backend and a measured LoRA fine-tune: design (2026-11-02)

Two linked pieces of work, each with a measured and honestly reported result. A negative or inconclusive result, written
up properly, counts as success. Source brief: `tasks/litellm-and-lora-finetune-agent-prompt.md`.

## Decisions agreed with the user

1. **Eval size.** The existing held-out set has only 16 distinct questions (6 document_qa, 2 summarisation,
   3 long_context, 2 multi_document, 3 negative_control). Per arm that gives intervals of about 25 points either way, so a
   base versus fine-tuned difference could not be seen. We build a new, larger held-out set from new open-licence
   documents that are never used for training, and still report the old 16 for continuity.
2. **Teacher.** Qwen2.5-72B-Instruct through an open-weight host. Same family as the student, a different family from
   the judge (`gpt-5.6-luna`). Its licence and the host's terms are checked and recorded before any data is generated.
3. **Spend.** Part 1 first. Nothing billable (GPU rental or a hosted teacher) happens until the user approves a priced
   plan with a cost cap.

## Part 1: LiteLLM behind the facade

- New setting `llm_backend: Literal["native", "litellm"] = "native"`. The native code is not removed or changed.
- `chat_complete()` and `chat_stream()` keep their signatures, decorators, `usage_sink`, timing spans and retry
  classification. When `llm_backend == "litellm"` they hand the call to `app/services/llm_litellm.py`.
- A LiteLLM `Router` is built from `settings` only. Keys and base URLs are passed explicitly, never read from the
  environment by LiteLLM.
- The fallback chain reproduces today's: groq model, then the optional groq fallback model, then openai; openai falls back
  to groq; mistral has none. `local` has no fallback and is never a fallback target.
- Our own `_is_retryable_llm_error` decides what may fall back. LiteLLM exceptions already carry `status_code`, so the
  existing classifier works on them. Streaming falls back only before the first token.
- The temperature rule stays in our code (drop on a 400 that mentions temperature, remember the model, record that it was
  not applied), so the judge's `temperature_applied` stays truthful.
- LiteLLM is an opt-in dependency (`requirements-litellm.txt`), imported lazily, so the scanned production images are not
  touched. If the backend is selected and the package is missing the error says so.

Evidence: mocked unit tests, a parity script against a local mock OpenAI-compatible server, guard-breaking checks, and a
measured table of what LiteLLM costs (import time, installed size, per-call overhead) and where it behaves differently.
No live parity is claimed unless a live provider is actually used.

## Part 2: LoRA fine-tune

Student: Qwen2.5-7B-Instruct (the family already benchmarked). Task: given retrieved chunks and a question, answer
using only that context, end with a `Sources:` section of exact source markers, and abstain correctly when the chunks do
not contain the answer. Prompts are built with the real `synthesizer._SYSTEM` and `_format_chunks`.

- **Data.** Open-licence or public-domain documents only, each recorded in a manifest (URL, licence, date, sha256). Split
  by document into train, validation and heldout-v2. The working-time declaration PDF and the Wikipedia RAG article are
  never used. A decontamination check (exact and word 8-gram overlap against the review packs, every `eval/` workload,
  the held-out workload and `retrieval_golden.json`) raises on a hit. Examples are filtered for schema, citation validity
  (every cited marker exists in the supplied chunks), duplicates and abstention rate, and a sample is checked by hand.
- **Training.** QLoRA or LoRA with `transformers`, `peft` and `trl`, fixed seed, all hyperparameters and versions
  recorded, smoke run before the full run. Adapters and weights stay out of git.
- **Evaluation.** The existing harness, unchanged where possible: same blinded pack builder, same judge model and prompt,
  same audits. Arms: base, fine-tuned, and one hosted model, on heldout-v2 (old 16 reported separately). Wilson 95%
  intervals. Results are labelled "LLM-assisted, not human-verified" until the user fills in the spot-check sheet.
- **Serving.** vLLM with LoRA enabled behind the existing `local` provider; throughput, p95 latency and capacity from
  `serving_load.py` and `capacity_plan.py`.

## Known risks, stated up front

- The judge is one LLM and samples at the provider default, so labels are not deterministic and not human-verified.
- The hosted arm (Groq `openai/gpt-oss-120b`) is the same model family as the judge, so a self-preference effect is
  possible. The report says so.
- A fine-tune on a few thousand synthetic examples can learn the teacher's style rather than better grounding. The report
  includes failure examples and the abstention results separately.
- Everything here is a single run on one GPU type.

## Out of scope

Voyage rerankers, MongoDB Atlas Vector Search, production configuration changes, deploying, pushing, committing weights or
datasets with licence doubts, and any CV or LinkedIn text.
