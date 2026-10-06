# Same-host serving and answer-generation evaluation

Run date: 2026-10-05. This run extends the BM25 retrieval comparison in
[`phase3-evaluation-2026-10-05.md`](phase3-evaluation-2026-10-05.md) with a
controlled FP16/AWQ/GPTQ serving comparison and retained generated answers.

## Setup

All three formats ran sequentially on one Secure L40S 48GB in US-MO-1 with the
same vLLM 0.30.0 image, Qwen2.5-7B-Instruct family, max model length 16,384,
GPU memory utilization 0.90, prefix caching enabled and request cache busting
enabled. FP16 used `Qwen/Qwen2.5-7B-Instruct`, AWQ used
`Qwen/Qwen2.5-7B-Instruct-AWQ`, and GPTQ used
`Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4`; both quantized variants were detected
from their model configs. This is a same-host comparison, unlike the earlier
cross-host GPTQ run retained in the October 1 report.

The price read before provisioning was $1.09/hour. The temporary pod was
terminated after all runs; a fresh account read showed no active pods. The
RunPod billing read had no posted line items yet, so it is not a billing
receipt. Based on about 61 minutes at the quoted hourly rate, estimated GPU
runtime was about $1.11, below the approved $5 cap. The existing network volume
was not mounted or modified.

Performance used the same eight captured DocChat prompts with their original
retrieved contexts, 1,400-token output cap and concurrency 1/4/16/32/64. The
request counts per cell were 8/4/16/32/64 respectively. Each format therefore
had 124 requests. Cache-hit rate was 0% and preemptions were 0 in all 15 cells.
The 8 prompts are a small, deliberately adversarial critic diagnostic set, not
a balanced production workload. They include unsupported DocChat-specific
questions against contexts that do not contain those implementation details.

## Serving results

Times are seconds. Decode throughput is the median per-request rate; aggregate
throughput is total output tokens divided by cell wall time.

| Format | Concurrency | OK/total | TTFT p50 / p95 | Total latency p50 / p95 | Decode tok/s p50 | Aggregate tok/s |
|---|---:|---:|---:|---:|---:|---:|
| FP16 | 1 | 8/8 | 1.00 / 1.36 | 4.50 / 8.85 | 48.7 | 39.7 |
| AWQ | 1 | 8/8 | 1.08 / 1.51 | 2.58 / 4.38 | 126.8 | 76.7 |
| GPTQ | 1 | 8/8 | 1.27 / 1.55 | 2.79 / 3.88 | 131.3 | 70.0 |
| FP16 | 4 | 4/4 | 1.66 / 2.49 | 6.68 / 7.43 | 36.1 | 101.8 |
| AWQ | 4 | 4/4 | 1.32 / 2.32 | 3.45 / 5.03 | 56.0 | 161.5 |
| GPTQ | 4 | 4/4 | 1.32 / 2.29 | 3.49 / 4.09 | 59.4 | 131.9 |
| FP16 | 16 | 16/16 | 4.48 / 8.96 | 13.34 / 18.00 | 24.9 | 180.9 |
| AWQ | 16 | 16/16 | 4.40 / 8.51 | 11.19 / 14.73 | 32.2 | 283.3 |
| GPTQ | 16 | 16/16 | 3.72 / 8.26 | 10.57 / 14.42 | 35.2 | 282.7 |
| FP16 | 32 | 32/32 | 8.28 / 17.64 | 22.89 / 28.07 | 13.4 | 219.3 |
| AWQ | 32 | 32/32 | 7.97 / 17.33 | 20.84 / 23.25 | 15.6 | 279.6 |
| GPTQ | 32 | 32/32 | 8.53 / 17.17 | 21.28 / 23.29 | 17.3 | 294.8 |
| FP16 | 64 | 64/64 | 17.97 / 40.07 | 48.06 / 57.11 | 7.0 | 233.4 |
| AWQ | 64 | 64/64 | 16.68 / 39.78 | 46.65 / 50.70 | 7.7 | 293.3 |
| GPTQ | 64 | 64/64 | 15.99 / 38.70 | 44.57 / 47.45 | 8.7 | 274.9 |

Compared with FP16, AWQ aggregate throughput was higher by 58.6%, 56.7%,
27.5% and 25.7% at concurrency 4/16/32/64. GPTQ was higher by 29.6%, 56.3%,
34.4% and 17.8%. At concurrency 1, both quantized formats had higher decode
rate but lower aggregate rate is not the right comparison for variable output
lengths; FP16's lower decode rate did not prevent a longer total latency. Do
not interpret these single-sweep deltas as confidence-bounded estimates.

The four-request concurrency cell has only four observations, so its p95 is
especially unstable. Each model also generated different output lengths. The
harness-reported GPU-time cost for the five measured cells summed to $0.0482
(FP16), $0.0361 (AWQ) and $0.0341 (GPTQ), excluding model download, startup and
idle time; these are not billed totals or equal-work cost comparisons.

Raw serving rows:
[`FP16`](phase3-serving-fp16.jsonl), [`AWQ`](phase3-serving-awq.jsonl),
[`GPTQ`](phase3-serving-gptq.jsonl).

## Generated answers and quality observations

The exact same eight captured prompts and retrieved contexts were generated
once with each format (24 completions total, all successful, temperature 0,
1,400-token cap). Non-streaming full-request latency median / observed maximum
was 5.33 / 9.51s for FP16, 2.70 / 5.97s for AWQ and 2.69 / 4.70s for GPTQ.
These figures are for eight diagnostic prompts, not a throughput statistic.

| Format | Successful answers | Answers with source-marker citation | Valid cited source markers |
|---|---:|---:|---:|
| FP16 | 8/8 | 0/8 | 0/0 |
| AWQ | 8/8 | 0/8 | 0/0 |
| GPTQ | 8/8 | 1/8 | 0/4 |

The GPTQ off-topic answer emitted four source-like markers, but none exactly
matched a source marker in its captured context. Thus source-marker coverage was
0/8, 0/8 and 0/8 respectively, and all citations that were emitted were
invalid. Full prompts, exact context and output text are retained in
[`FP16`](phase3-answers-fp16.jsonl), [`AWQ`](phase3-answers-awq.jsonl), and
[`GPTQ`](phase3-answers-gptq.jsonl).

This small diagnostic exposes a grounding weakness: responses often acknowledged
that the context lacked a DocChat-specific answer, then continued with generic
outside-context advice. Examples include proposing generic vector-store choice
criteria and inventing a typical PDF chunking workflow/libraries. Answers that
discussed RAG and transformer attention were on topic, but still omitted valid
source markers. This is a qualitative review of this small, adversarial set;
there is no adjudicated claim-level unsupported-claim rate here. A separate
reviewer should annotate atomic claims against the exact context before using
`eval/answer_quality.py` to publish groundedness/completeness scores.

The prior FP16/AWQ/GPTQ critic diagnostic remains separate: it measured a
classifier on edge cases and corruptions. It is not used as a proxy for these
generated-answer observations, and this run did not re-run the critic.

## Conclusion and limits

This is a reproducible same-host serving and generation comparison and a useful
resume-worthy infrastructure result: real DocChat-shaped prompts, five load
levels, three quantization formats, TTFT/latency/decode/aggregate throughput,
and retained output/evidence pairs. Under this short run, both quantized formats
improved aggregate throughput over FP16 at concurrency 4/16/32/64. The small
generation audit found zero valid source citations for all formats and examples
of unsupported generalization. No quality winner is established, and no
production model, critic, or retriever change is recommended from this dataset.

Next quality work: build a held-out set across document QA, summarization,
long-context and multi-document tasks; label expected facts; double-review a
meaningful sample of answer claims and citations; then aggregate with
`eval/answer_quality.py`. Repeat the concurrency sweep before capacity decisions
and compare at least two independent runs per format.
