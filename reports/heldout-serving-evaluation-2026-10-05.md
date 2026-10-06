# Held-out DocChat serving and answer evaluation

Run date: 2026-10-05. This extends the critic-focused serving run with a broader
DocChat workload and two measured repeats per concurrency. Retrieval-only
results remain in [`phase3-evaluation-2026-10-05.md`](phase3-evaluation-2026-10-05.md).

## Workload and method

The held-out manifest contains 40 actual DocChat prompt/context pairs: 24
development questions and 16 held-out additions, including six new document-QA
questions, two summaries, three long-context questions, two multi-document
questions and three negative controls. Every request uses the captured
retrieval context and per-case output cap. The workload fingerprint is
`65e6df6515525e1ea78ab54631400f9702b0b7bc4ccc89f2c2846b9c8a6c06a9`; the
source corpus fingerprint is
`f73d2b6f83281bf4d83c4794aecf47eccc98696de8f60e7b818616ed35d0cf04`.

Each format ran 64 measured requests per cell at concurrency 1, 4, 16, 32 and
64, twice, plus warmups: 640 measured requests per format, 1,920 total. All
requests succeeded. The runs used one Secure L40S in US-MO-1, vLLM 0.30.0,
Qwen2.5-7B-Instruct family, 16,384 max model length, 0.90 GPU memory
utilization, prefix caching and cache-busting requests. Sampling used provider
defaults, so output lengths and answers vary; no confidence intervals were
computed.

## Performance

Values below average the two repeats. p95 is the worse of the two repeat p95s;
throughput is successful requests per second. Output throughput is generated
tokens per second across the cell.

| Format | Concurrency | RPS | p95 latency | p95 TTFT | Output tok/s | Error rate |
|---|---:|---:|---:|---:|---:|---:|
| FP16 | 1 | 0.271 | 9.11 s | 1.08 s | 39.5 | 0% |
| FP16 | 4 | 0.912 | 10.88 s | 1.29 s | 132.5 | 0% |
| FP16 | 16 | 2.029 | 17.70 s | 2.91 s | 301.7 | 0% |
| FP16 | 32 | 2.083 | 21.78 s | 7.10 s | 302.4 | 0% |
| FP16 | 64 | 2.064 | 26.45 s | 15.44 s | 293.4 | 0% |
| AWQ | 1 | 0.598 | 3.89 s | 0.97 s | 85.2 | 0% |
| AWQ | 4 | 1.793 | 4.44 s | 0.99 s | 241.1 | 0% |
| AWQ | 16 | 2.971 | 12.05 s | 2.70 s | 423.5 | 0% |
| AWQ | 32 | 3.050 | 17.87 s | 6.57 s | 439.6 | 0% |
| AWQ | 64 | 3.073 | 20.06 s | 14.99 s | 427.4 | 0% |
| GPTQ | 1 | 0.622 | 3.54 s | 0.92 s | 84.4 | 0% |
| GPTQ | 4 | 1.820 | 4.65 s | 0.98 s | 251.5 | 0% |
| GPTQ | 16 | 3.023 | 11.97 s | 2.42 s | 410.5 | 0% |
| GPTQ | 32 | 3.131 | 18.03 s | 6.40 s | 427.7 | 0% |
| GPTQ | 64 | 3.037 | 19.96 s | 15.31 s | 411.0 | 0% |

At this workload and a 20-second p95 SLO, the capacity tool selects FP16 at
concurrency 16 (mean 2.03 RPS), AWQ at 32 (3.05 RPS), and GPTQ at 32 (3.13
RPS). The conservative planning rates apply 30% headroom to the slower repeat:
1.388, 2.088 and 2.166 RPS per GPU respectively. For a 5-RPS target this
estimates 4 FP16 GPUs or 3 GPUs for either quantized format. At the quoted
$1.09/GPU-hour, estimated fleet cost is $4.36/hour FP16 and $3.27/hour AWQ or
GPTQ. This assumes linear horizontal scaling and is a planning bound, not a
multi-GPU measurement. GPTQ at concurrency 64 narrowly meets the SLO but has
lower mean throughput than 32; AWQ at 64 slightly misses it. FP16 at 32 and 64
misses it.

These mixed-workload results supersede the earlier small critic-only capacity
signal. They are still not production capacity guarantees: the source corpus
has only 17 chunks from two documents, this is a short closed-loop replay, and
the prompt/query mix is limited. Exact deployment details and every repeat are
in [`heldout-serving-fp16`](heldout-serving-fp16/),
[`heldout-serving-awq`](heldout-serving-awq/) and
[`heldout-serving-gptq`](heldout-serving-gptq/). Capacity assumptions and
per-level results are in [`capacity-plan.json`](capacity-plan.json).

AWQ and GPTQ runs captured 327 and 314 one-second vLLM metric samples,
including waiting-request gauges. The FP16 run predates metric polling. The
load generator records TTFT, total latency, service time, and scheduling lag;
it does not currently separate engine queue-wait seconds from prefill. Treat
TTFT and total latency as including any queueing. Queue gauge snapshots are
useful diagnostics, not per-request queue distributions.

## Retrieval and answer-quality evidence

The same 24-question retrieval evaluation found Recall@3 of 0.875 for dense,
0.917 for BM25, 0.979 for dense plus overlap reranking, and 1.000 for dense
plus cross-encoder reranking. The full report documents that these are
development-set numbers on the tiny two-source corpus; the rerankers share the
dense candidate set.

All three model formats generated 40/40 successful answers. A mechanical
source-marker audit is in [`heldout-citation-audit.json`](heldout-citation-audit.json).
On the 16 held-out cases, citation-bearing answer coverage was 18.75% for FP16,
6.25% for AWQ and 6.25% for GPTQ. Exact context-marker validity among emitted
markers was 100% for FP16 (27 markers), 100% for AWQ (1), and 50% for GPTQ (2
of 4). These counts combine different task categories and are very small. The
audit only checks whether a printed bracket marker exactly exists in the
provided context; it does not verify claim support, completeness or
groundedness.

A blinded 120-row review pack (40 cases × 3 formats) is in
[`quality-review-pack.jsonl`](quality-review-pack.jsonl). It retains each
answer with its exact context and expected facts, while hiding the model key.
The corresponding unblinding key is deliberately outside the repository at
`/private/tmp/docchat-quality-review-key.json`. Human claim-support,
unsupported-claim and abstention labels have not yet been entered. Therefore no
groundedness or unsupported-claim score is reported. A reviewer should label
atomic claims against the supplied context, with a second reviewer checking a
substantial sample and disagreements adjudicated, then run
`eval.score_answer_review_pack`.

## Cost and limitations

The temporary L40S pod (`xurcmwnkzwdkat`) has been terminated and a follow-up
pod read returned 404. The pod-billing endpoint currently reports $0.638 in
posted pod charges through the bucket ending 11:00 UTC; billing can lag and
this is not a final invoice. The rate used by the capacity model is the
pre-provision quote of $1.09/hour. No model-quality winner is established
until human review is complete. FP16 deployment metadata was documented in
the separate checked-in deployment manifest; its benchmark artifact did not
embed that manifest, unlike the AWQ and GPTQ run artifacts.
