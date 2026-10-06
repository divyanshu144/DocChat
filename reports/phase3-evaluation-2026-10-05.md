# Phase 3 retrieval and serving evaluation

Run date: 2026-10-05. Retrieval numbers below were generated locally from the
existing Qdrant `source_chunks` collection and the checked-in 24-question golden
set. A same-host L40S serving and generation comparison was subsequently run;
full setup, results, answer audit, and limitations are in
[`phase3-serving-quality-2026-10-05.md`](phase3-serving-quality-2026-10-05.md).
The expanded 40-case, two-repeat serving evaluation and capacity model are in
[`heldout-serving-evaluation-2026-10-05.md`](heldout-serving-evaluation-2026-10-05.md).

## Retrieval quality and cost

The collection contained 17 chunks from two sources. The golden set has 24
single-annotator questions with chunk relevance labels. Dense uses exact CPU
cosine over stored vectors and up to 24 candidates. BM25 tokenizes and searches
the full 17-chunk corpus. `dense_overlap_rerank` and `cross_encoder` reorder the
same dense candidate pool and are not independent candidate-generation methods.
All methods are truncated to 12 results for ranking metrics.

| Method | Recall@1 | Recall@3 | Recall@5 | MRR@12 | Mean ranking time/query |
|---|---:|---:|---:|---:|---:|
| Dense cosine | 0.729 | 0.875 | 0.958 | 0.911 | 0.143 ms |
| Full-corpus BM25 | 0.833 | 0.917 | 0.958 | 0.967 | 0.919 ms |
| Dense + overlap rerank | 0.792 | 0.979 | 1.000 | 0.958 | 0.132 ms* |
| Dense + cross-encoder rerank | 0.854 | 1.000 | 1.000 | 1.000 | 1170.31 ms* |

`*` Reranking time only; dense candidate generation is a separate span. BM25
time includes tokenization, corpus term statistics and scoring for each query.
The corpus is so small that BM25's Python implementation has overhead; these
times are not representative of a production index. The cross-encoder's roughly
1.17-second CPU ranking cost is too high for an unexamined default in an
interactive request path.

On this fixture, BM25 improved Recall@3 by 4.2 percentage points over dense
cosine; dense overlap reranking improved it by 10.4 points and cross-encoder by
12.5 points. These are development-set comparisons only. The high baseline
recall, correlated query variants, two-source corpus and lack of independent
annotation make generalization uncertain. They do not justify changing the
production ranker. Raw per-case rankings, corpus digest and run metadata are in
[`retrieval-eval-phase3.json`](retrieval-eval-phase3.json). The historical
October 1 report remains separately labeled in
[`retrieval-evaluation.md`](retrieval-evaluation.md).

## Serving performance and quality evidence

The earlier quantization study served Qwen2.5-7B-Instruct on an L40S 48GB
through vLLM at concurrency 1, 16 and 64; its limitations and historical data
remain in [`quantization-2026-10-01/README.md`](quantization-2026-10-01/README.md).
The new same-host run compares FP16, AWQ and GPTQ at concurrency 1, 4, 16, 32
and 64, with eight DocChat prompt/context pairs. It completed 124 requests per
format with no errors. See the linked serving report for the full table and raw
rows.

In the new same-host run, AWQ aggregate throughput versus FP16 was higher by
58.6%, 56.7%, 27.5% and 25.7% at concurrency 4/16/32/64; GPTQ was higher by
29.6%, 56.3%, 34.4% and 17.8%. These are single sweeps, with variable output
lengths and no confidence intervals. The concurrency-4 p95 estimates use only
four requests. They are useful infrastructure measurements, not stable capacity
or quality conclusions.

The saved “quality” measurements are critic classification diagnostics, not
final-answer groundedness measurements: FP16 and AWQ caught 15/15 synthetic
corruptions, GPTQ caught 9/15 and returned parse-invalid JSON for 6; the small
edge-case set was 1/5, 3/5 and 1/5 correct respectively. These results indicate
critic-format and decision behavior on that test set. They do not estimate
answer quality, citation coverage, factual support or retrieval-conditioned
answer completeness.

## Answer quality coverage

Generated answers paired with their exact captured prompts and contexts are now
saved for all three formats (eight per format). The raw files and a source-marker
audit are linked in the serving report. This is not a reviewed claim/citation
annotation set: no aggregate groundedness or unsupported-claim score is
reported, and critic verdicts remain separate from final-answer quality.

The scorer expects case IDs, expected answer fact IDs, retrieved context IDs,
emitted citation IDs, human-labeled claims and their citations, and expected vs
observed abstention. The expanded held-out workload now exists and pairs each
answer with exact context. Human support/citation labels still need blind
double-review on a substantial sample, with disagreements adjudicated. See the
held-out report for the reviewer pack and its limits.

## Reproduction and remaining work

The retrieval run used:

```sh
venv/bin/python -m eval.retrieval_eval \
  --qdrant-url http://localhost:6333 \
  --embedding-cache-dir /Users/divyanshu/.cache/fastembed \
  --output reports/retrieval-eval-phase3.json
```

No production retrieval behavior changed. The new generation and serving run
used temporary L40S pods that have been terminated; see the linked reports for
runtime-cost evidence and raw measurements. To complete answer-quality
evaluation, annotate the paired outputs against their exact contexts, ideally
with blind double review. The expanded GPU matrix has two repeats per
concurrency level, but capacity remains provisional because the corpus and
workload are small. Do not claim a serving-format quality winner until human
answer review is complete.
