# Fine-tuning Qwen2.5-7B-Instruct to answer from retrieved context: what was measured

Date: 2026-11-03. Branch: `feat/litellm-lora-finetune`. Every number below comes from a file in
`reports/finetune-run-2026-11-03/` or from the commands listed at the end.

## Summary

A LoRA adapter was trained on 355 examples so that Qwen2.5-7B-Instruct follows the answer format this app asks for: answer from the
supplied context, list the sources used under a final `Sources:` heading with the exact markers, use no Markdown, and say so briefly
when the context does not contain the answer. The adapter was compared with the unmodified model on **99 new questions about 15
documents that were never used for training**, and, separately, on the older 16-question held-out set and its 24 development cases.

**What the numbers show.** On the new held-out set the base model almost never produces the required Sources section (1 of 84
answerable questions), so 0 of 84 answers are well formed. The tuned model produces a well-formed answer for 69 of 84. It also gives a short
abstention on 14 of the 15 negative controls, where the base model does so on 3 of 15. It gave a short refusal to none of the 84
answerable questions (the base model to 2). Serving the adapter on top of the base model cost about 3 to 10 percent of throughput
(tokens per second down 3 to 9 percent, requests per second down 8 to 10 percent) at concurrency 8 and 32 in a short test.

**What the numbers do not show.** Nothing here measures whether the answers are true or complete. No LLM judge or human verdict was
produced, because the OpenAI and Anthropic accounts have no credit and Groq's free daily token limit is smaller than the job (details
below). The hosted gpt-oss-120b arm was not measured for the same reason. The gain is in format, citations and abstention behaviour. On
the old held-out documents (a PDF and a Wikipedia article, unlike the training material) the gain is much smaller and rests on 13
answerable cases. Do not read this as "the fine-tuned model is better". Read it as "the fine-tuned model follows the output contract and
the base model, with this prompt, does not".

## Data

| Item | Value |
|---|---|
| Source documents | 56 open-licence documents: 48 GOV.UK guides (Open Government Licence v3.0) and 8 NIST publications (each states it is not subject to copyright in the US). Hashes in `finetune/sources.lock.json`. |
| Splits (by document) | 34 train, 4 validation, 15 held out, 3 excluded for sharing text with held-out documents |
| Teacher | Qwen2.5-72B-Instruct (AWQ build `Qwen/Qwen2.5-72B-Instruct-AWQ`) served by vLLM 0.30.0 on one A100 80GB. Under the Qwen licence, using outputs to train another model is allowed; a model that is distributed must say "Built with Qwen" or "Improved using Qwen" and carry the licence notice (Sections 5(b) and 3(c)). I read this through a fetch tool's summary, not the full text, so read the LICENSE file in the `Qwen/Qwen2.5-72B-Instruct` repository before sharing the adapter. |
| Student | Qwen2.5-7B-Instruct (its model card states Apache-2.0) |
| Raw examples | 1289 (1,175 from the first pass and 114 abstentions from the strict method below) |
| Passed format and citation rules | 535 |
| After capping abstentions at 15% | 475 |
| After removing examples that share an 8-gram with an evaluation file or a held-out question | **405** (355 train, 50 validation), 62 of them abstentions (15.3%), covering all 38 training and validation documents |
| Held-out set | 99 cases from the 15 held-out documents: 60 document questions, 8 summaries, 8 long-context, 8 multi-document, 15 negative controls. The questions are LLM-written by the teacher. |

The teacher's answers were checked mechanically (format, that every cited marker exists in the context, no duplicates, abstention
wording) and by me reading 8 random examples. They were **not** fact-checked against their contexts, so some training answers may be
wrong. Only 535 of 1289 raw examples passed the rules, because the teacher often added Markdown, left out the Sources
section, or cited sources in an abstention.

### Leakage checks, and the decisions made after seeing the numbers

- Document level: no held-out document shares an 8-gram with any evaluation file. Training documents carry at most 1.4% (mean 0.4%) of a
  held-out document's text, after ignoring stock text (8-grams that appear in three or more training-side documents, 704 of them).
- Example level: after the removals below, none of the 405 examples shares an 8-gram with the old evaluation files or with the 99
  held-out questions and their expected facts. The held-out documents' text found anywhere in the examples is at most
  1.36% per document (mean 0.34%), under the 2% cap I set.
- **These rules were chosen after seeing the overlap numbers.** The stock-text rule, the three excluded training documents, the 2% cap,
  and the removal of 70 examples (mostly shared eligibility wording and contact lines) were all decided after a first check flagged every
  example. That first check was also wrong in a way worth recording: it counted the prompt's own scaffolding as leakage (see `tasks/lessons.md`).
- Some held-out guides are topically close to training guides (for example student loans). No text overlap was found, but the topics are related.

### A flaw found and fixed during the run

The first abstention examples asked the teacher for questions "not answered by this excerpt". Retrieval searches the whole document, which
often answers them, so 91% of those attempts were real answers, and the first 15 held-out negative controls were not reliably negative.
Both were rebuilt: a question is borrowed from a different document and kept only when a strict teacher check says the retrieved context
cannot answer it. The first version of the held-out set was discarded before anything was evaluated on it.

## Training

| Item | Value |
|---|---|
| Method | QLoRA: 4-bit NF4 base, bf16 compute, adapter on all attention and MLP projections |
| Adapter | rank 16, alpha 32, dropout 0.05; 40,370,176 trainable of 7,655,986,688 parameters (0.53%) |
| Settings | learning rate 0.0002, cosine schedule, warmup 3%, effective batch 16, 3 epochs, max length 5120, seed 42 |
| Loss | on the answer only; the prompt is masked |
| Validation loss by epoch | epoch 1: 0.244, epoch 2: 0.253, epoch 3: 0.265 |
| Adapter used | the epoch-1 checkpoint (lowest validation loss), so the model was selected on 50 validation examples |
| Mean training loss | 0.193 |
| Time | 36 minutes including model load, on one L40S 48GB |
| Libraries | torch 2.8.0+cu128, transformers 4.57.6, peft 0.21.2, CUDA 12.8 (full list in `pip-freeze-training-env.txt`) |
| Adapter file | `adapter_model.safetensors`, sha256 `9fbf8dcc4b73b5e306b8db6f216fbeb8980d0026a01c4db7f3b7d9063967e8f8`. Not committed. |

Validation loss was lowest after the first epoch and rose afterwards, which points to overfitting on a small set. One seed, one
setting, no variance estimate.

## Evaluation

Both models were served by vLLM 0.30.0 on one L40S (base `Qwen2.5-7B-Instruct`, with the adapter loaded as a second model name on the same
server) and queried at temperature 0 with the exact prompts the app builds. Answers were checked mechanically by
`eval/answer_behaviour_metrics.py`, which needs no judge. An error or empty answer counts as a failure in the denominator. The "short
abstention" variant (under 500 characters) was added after the first run showed that the loose phrase match credited the base model for
long answers that merely mention a gap; both are shown.

**New held-out set (99 questions about 15 unseen documents)** (99 cases: 84 answerable, 15 negative controls). Cells are correct/total = rate (95% Wilson interval, percent).

| Measure | Base Qwen2.5-7B-Instruct | Tuned (adapter) |
|---|---|---|
| Well-formed answer (all format checks pass, not a refusal) | 0/84 = 0.0% (0 to 4) | 69/84 = 82.1% (73 to 89) |
| Has a Sources section with a marker | 1/84 = 1.2% (0 to 6) | 78/84 = 92.9% (85 to 97) |
| Every cited marker was in the supplied context | 1/84 = 1.2% (0 to 6) | 77/84 = 91.7% (84 to 96) |
| No markers inside the answer text | 79/84 = 94.0% (87 to 97) | 82/84 = 97.6% (92 to 99) |
| No Markdown headings or bold | 50/84 = 59.5% (49 to 69) | 71/84 = 84.5% (75 to 91) |
| False refusal (short abstention on an answerable question) | 2/84 = 2.4% (1 to 8) | 0/84 = 0.0% (0 to 4) |
| Hit the token limit | 3/84 = 3.6% (1 to 10) | 3/84 = 3.6% (1 to 10) |
| Negative controls: short abstention | 3/15 = 20.0% (7 to 45) | 14/15 = 93.3% (70 to 99) |
| Negative controls: says the context lacks it (loose) | 14/15 = 93.3% (70 to 99) | 14/15 = 93.3% (70 to 99) |

Paired on the same cases (exact test on the cases where the two differ): well-formed answers, tuned only 69 vs base only 0, p < 0.0001; false refusals, tuned only 0 vs base only 2, p = 0.5; short abstentions on negative controls, tuned only 11 vs base only 0, p = 0.001.

**Old held-out set (16 questions about a working-time PDF and a Wikipedia article)** (16 cases: 13 answerable, 3 negative controls). Cells are correct/total = rate (95% Wilson interval, percent).

| Measure | Base Qwen2.5-7B-Instruct | Tuned (adapter) |
|---|---|---|
| Well-formed answer (all format checks pass, not a refusal) | 1/13 = 7.7% (1 to 33) | 4/13 = 30.8% (13 to 58) |
| Has a Sources section with a marker | 1/13 = 7.7% (1 to 33) | 12/13 = 92.3% (67 to 99) |
| Every cited marker was in the supplied context | 1/13 = 7.7% (1 to 33) | 7/13 = 53.8% (29 to 77) |
| No markers inside the answer text | 12/13 = 92.3% (67 to 99) | 12/13 = 92.3% (67 to 99) |
| No Markdown headings or bold | 3/13 = 23.1% (8 to 50) | 6/13 = 46.2% (23 to 71) |
| False refusal (short abstention on an answerable question) | 0/13 = 0.0% (0 to 23) | 0/13 = 0.0% (0 to 23) |
| Hit the token limit | 1/13 = 7.7% (1 to 33) | 1/13 = 7.7% (1 to 33) |
| Negative controls: short abstention | 2/3 = 66.7% (21 to 94) | 2/3 = 66.7% (21 to 94) |
| Negative controls: says the context lacks it (loose) | 3/3 = 100.0% (44 to 100) | 2/3 = 66.7% (21 to 94) |

Paired on the same cases (exact test on the cases where the two differ): well-formed answers, tuned only 3 vs base only 0, p = 0.25; false refusals, tuned only 0 vs base only 0, p = 1; short abstentions on negative controls, tuned only 0 vs base only 0, p = 1.

With 13 answerable cases the intervals are very wide. The tuned model usually writes a Sources section here (12 of 13) but only 7 of 13 use
markers that were in the context, so the format learning transfers only partly to documents of a different kind.

**Old development set (24 cases from the same two documents; reported apart and not pooled)** (24 cases: 24 answerable, 0 negative controls). Cells are correct/total = rate (95% Wilson interval, percent).

| Measure | Base Qwen2.5-7B-Instruct | Tuned (adapter) |
|---|---|---|
| Well-formed answer (all format checks pass, not a refusal) | 0/24 = 0.0% (0 to 14) | 21/24 = 87.5% (69 to 96) |
| Has a Sources section with a marker | 0/24 = 0.0% (0 to 14) | 24/24 = 100.0% (86 to 100) |
| Every cited marker was in the supplied context | 0/24 = 0.0% (0 to 14) | 24/24 = 100.0% (86 to 100) |
| No markers inside the answer text | 24/24 = 100.0% (86 to 100) | 24/24 = 100.0% (86 to 100) |
| No Markdown headings or bold | 15/24 = 62.5% (43 to 79) | 21/24 = 87.5% (69 to 96) |
| False refusal (short abstention on an answerable question) | 0/24 = 0.0% (0 to 14) | 0/24 = 0.0% (0 to 14) |
| Hit the token limit | 0/24 = 0.0% (0 to 14) | 0/24 = 0.0% (0 to 14) |

Paired on the same cases (exact test on the cases where the two differ): well-formed answers, tuned only 21 vs base only 0, p < 0.0001; false refusals, tuned only 0 vs base only 0, p = 1; short abstentions on negative controls, tuned only 0 vs base only 0, p = 1.

Cross-check: the repository's existing citation audit (`eval.audit_answer_citations`), pooled over both held-out sets (115 answers per
model), gives citation coverage of 7% for the base model and 79% for the tuned one, with citation precision 1.00 and 0.93.

### Serving cost

| Concurrency | Model | Requests ok (errors) | Requests per second | p50 latency (s) | p95 latency (s) | Output tokens per second |
|---|---|---|---|---|---|---|
| 1 | base | 6 (0) | 0.20 | 3.27 | n/a (too few) | 41 |
| 1 | base + adapter | 6 (0) | 0.17 | 2.79 | n/a (too few) | 40 |
| 8 | base | 43 (0) | 1.10 | 5.52 | 13.2 | 208 |
| 8 | base + adapter | 39 (0) | 1.01 | 5.57 | 17.9 | 202 |
| 32 | base | 80 (1) | 2.16 | 12.18 | 30.7 | 378 |
| 32 | base + adapter | 78 (0) | 1.95 | 12.22 | 34.5 | 345 |

Closed loop, 30 second windows, one repeat, prefix cache bypassed, from a laptop through Runpod's HTTP proxy (about 270 ms round trip), so
treat these as indicative. With the adapter, output tokens per second were 3% to 9% lower and requests per second 8% to 10% lower at concurrency 8 and 32,
and latency was in the same range. One repeat cannot separate that from noise.

## What was not done, and why

- **No LLM judge, so no claim about correctness.** The earlier evaluation used `gpt-5.6-luna` through OpenAI. That account now returns
  "no credits remaining", and the Anthropic account says its credit balance is too low. No Mistral key is configured. Groq works, but its
  free tier allows 200,000 tokens a day for `openai/gpt-oss-120b`, which is far below the roughly 1.7 million tokens that about 350 judgments need.
- **No hosted gpt-oss-120b arm.** The same Groq limit applies (about 600,000 tokens for 139 prompts). The first trial also exposed a
  silent hazard: with the app's fallback on, rate-limited Groq calls had been answered by OpenAI. The generator now disables fallback,
  writes each row as it finishes, stops cleanly at the daily limit and resumes with `--resume`.
- **No human spot-check.** The blinded review packs are built (`data/finetune/eval/pack-v2.jsonl` and `pack-old.jsonl`). The verdicts are
  yours to fill in once a judge has labelled them.

## Limitations

1. The metrics are mechanical. They show that the output contract is followed, not that answers are right.
2. The base model was given the app's prompt as it is. That it ignores the Sources instruction is a finding about this prompt and model. A
   few-shot prompt or a stricter instruction might narrow the gap, and I did not test one.
3. The training questions, the held-out questions and the teacher answers all come from one model family, which is also the student's
   family, so the in-domain result is probably optimistic.
4. All 15 held-out documents are GOV.UK or NIST, like the training documents. The weaker old-held-out result is the only evidence about
   other material, and it rests on 13 cases.
5. The 15 negative controls give an interval of 70% to 99% for the tuned model. Do not read fine differences into it.
6. One training run, one seed, one setting, and an adapter picked by validation loss on 50 examples.
7. The serving test is short and goes through a public proxy.
8. Several rules were set after seeing data (listed above).

## Things that went wrong

- The first teacher pod vanished after about 45 minutes with no stop request. The run died and only 76 examples were on disk. Generation
  now saves each document as it finishes and resumes.
- The abstention flaw described above.
- The example-level leakage check flagged all 475 examples on real data even though its tests passed.
- Two process errors of mine: a wait loop that matched its own `pgrep` and cost about 9 minutes of GPU, and one commit made while two
  tests failed (a settings leak from a new test), fixed in the next commit.
- A vLLM start failed on a missing `ninja` and I noticed it eight minutes late.

## Cost

Runpod, as posted by the billing API when this was written: $4.07. The last hours had not posted yet, so the total is estimated from pod
run times at about $5.1: teacher pods about $3.7 (three rentals of roughly 45, 59 and 19 minutes at $1.79 an hour) and the training and
serving pod about $1.4 (78 minutes at $1.09 an hour). There was no OpenAI or Anthropic spend (both calls failed for lack of credit), and
Groq was on the free tier. The cap was $25 for everything.

## Reproduce

Data and tooling: `finetune/README.md`. Training: `finetune/train_lora.py` with `requirements-finetune.txt`. Metrics:
`python -m eval.answer_behaviour_metrics --run base:v2:<answers> --run tuned:v2:<answers> --pair tuned:base`. The generated data,
answers, adapter and review packs are in git-ignored `data/finetune/` and `finetune/artifacts/`. Hashes of the training files are in
`training-run.json`.

To finish the judged comparison once a judge has credit:

```bash
python -m eval.judge_answer_review_pack --pack data/finetune/eval/pack-v2.jsonl --output data/finetune/eval/labels-v2.jsonl \
    --judge-provider openai --judge-model gpt-5.6-luna --prompt-version v1
python -m eval.aggregate_judge_labels --labels data/finetune/eval/labels-v2.jsonl --pack data/finetune/eval/pack-v2.jsonl \
    --key data/finetune/eval/pack-v2.key.jsonl
python -m eval.generate_hosted_answers --prompts data/finetune/heldout-v2-workload.json \
    --output data/finetune/eval/answers-hosted-v2.jsonl --resume   # repeat daily until it reports 0 not tried
```
