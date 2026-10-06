# Retrieval and answer-quality evaluation

Phase 3 adds offline retrieval comparisons, answer capture, and an
annotation-driven answer scorer. These tools do not change DocChat's production
retriever. Answer capture calls the configured OpenAI-compatible local inference
endpoint; the retrieval and scoring tools run offline.

## Retrieval comparisons

`python -m eval.retrieval_eval` compares exact CPU dense cosine retrieval with
BM25 over the complete exported corpus. BM25 uses a small, dependency-free
tokenizer and the standard length-normalized term-frequency score; it is a
transparent baseline, not a production search implementation. The existing
overlap reranker and cross-encoder reranker both re-order the same dense
candidate pool. The report calls this out as `dense_overlap_rerank` and
`cross_encoder`, so their scores are not mistaken for independent retrieval.

Report Recall@1/3/5, MRR, per-query rankings, and ranking time. Dense/cross-encoder
comparisons must use the same corpus digest, query set, dense candidate limit,
and final ranking limit. BM25 searches the full corpus and has its own corpus
count. Its timing excludes file loading and query preparation. The current
golden set is a small, single-annotator development fixture from two sources;
it is useful for checking the harness, not for choosing a production default.
Expand and independently review labels before making generalization claims.

Example with an existing Qdrant scroll export (payload text and stored vectors
are required):

```sh
python -m eval.retrieval_eval --corpus-file /path/to/qdrant-scroll.json \
  --golden-set eval/retrieval_golden.json --output /path/to/retrieval-report.json
```

The command can also connect to configured Qdrant when `--corpus-file` is
omitted. That operation reads the live collection; prefer a frozen corpus
export for reproducible comparisons. Cross-encoder evaluation may download its
CPU model on first use. A GPU is not required.

## Held-out workload and blind review

`data/heldout-quality-workload.json` is a source-grounded 40-case snapshot of
the current local Qdrant collection: 24 development questions from the existing
retrieval fixture and 16 held-out additions (six new document-QA questions,
summaries, long-context tasks, multi-document questions and negative controls).
The corpus digest and exact messages are embedded. DocChat's query embedder,
Qdrant search, reranker and synthesis context formatter build each prompt; source
selection is pinned to keep runs comparable, and no planner LLM call is needed.
The collection has only two documents, so this is query-held-out evaluation, not
an independent-corpus benchmark. The 24 existing questions remain in the mixed
serving workload for task diversity; score the held-out split separately.

Rebuild the snapshot against the currently ingested collection (the command
refuses to overwrite an existing output):

```sh
python -m eval.prepare_quality_workload \
  --qdrant-url http://localhost:6333 \
  --output data/heldout-quality-workload.json
```

With `LOCAL_BASE_URL` and (optionally) `LOCAL_API_KEY` set, generate answer/evidence
pairs for any OpenAI-compatible local server. The output retains exact messages,
answer, status, token usage and latency, and uses the per-case output caps:

```sh
python -m eval.generate_answer_samples \
  --prompts data/heldout-quality-workload.json \
  --output reports/answers-format-repeat.jsonl --model Qwen2.5-7B-Instruct
```

Exact marker coverage can be audited before human claim review; this only checks
whether an emitted marker occurs in that answer's context, not whether its claims
are grounded:

```sh
python -m eval.audit_answer_citations reports/answers-fp16.jsonl \
  reports/answers-awq.jsonl reports/answers-gptq.jsonl \
  --output reports/answer-citation-audit.json
```

After collecting outputs from all formats and repeats, create a blinded reviewer
pack and keep its unblinding key private. The pack joins each answer to exact
evidence, supplies source markers and gold QA facts, and leaves claim support
labels blank for human review:

```sh
python -m eval.build_answer_review_pack \
  --workload data/heldout-quality-workload.json \
  --answers reports/answers-a.jsonl reports/answers-b.jsonl \
  --output reports/quality-review-pack.jsonl \
  --key /private/tmp/docchat-quality-review-key.json
```

Have two reviewers independently label atomic claims, fact coverage, citations
and abstentions, then adjudicate disagreements before transforming the reviewed
rows to the scorer schema. Do not fill support labels with model-generated
judgments. The additional held-out tasks beyond document QA need their expected
facts authored by reviewers from the supplied contexts.

After reviewers have filled every claim's `supported` label and each case's
`review.abstained`, score the pack with `python -m eval.score_answer_review_pack
reports/quality-review-pack.jsonl --output reports/answer-quality-reviewed.json`.
This reports development and held-out splits separately and rejects unlabeled
claims or abstentions instead of silently assigning them a score.

The 2026-10-05 same-host measurements and generated-answer audit remain in
[`phase3-serving-quality-2026-10-05.md`](../reports/phase3-serving-quality-2026-10-05.md).

## Capacity estimation

After every format has at least two complete repeated cells per tested
concurrency, estimate conservative one-GPU throughput and cost:

```sh
python -m eval.capacity_plan reports/heldout-serving-fp16 \
  reports/heldout-serving-awq reports/heldout-serving-gptq \
  --latency-slo 20 --max-error-rate 0.01 --headroom 0.70 \
  --target-rps 5 --hourly-cost 1.09 \
  --output reports/capacity-plan.json
```

The estimate uses the minimum observed repeat throughput times the explicit
headroom factor. It excludes retrieval/database capacity and extrapolates GPU
counts linearly, so validate horizontal scaling and the full DocChat path before
committing to hardware or spend.

## Scorer input

`eval.answer_quality` aggregates claim and citation labels provided by a human.
It does not decide whether a claim is factually supported, and it does not call
an LLM judge. Each answer case records the IDs of context chunks, expected answer
fact IDs, answer claims, claim-to-fact IDs, human support labels, claim citation
IDs, all emitted citation IDs, and whether abstention was expected and observed.

Minimal input shape:

```json
{
  "schema_version": 1,
  "cases": [{
    "id": "qa-001",
    "expected_fact_ids": ["weekly-limit"],
    "context_ids": ["chunk-17"],
    "cited_ids": ["chunk-17"],
    "expected_abstention": false,
    "abstained": false,
    "claims": [{
      "id": "claim-1",
      "text": "The stated average limit is 48 hours per week.",
      "fact_ids": ["weekly-limit"],
      "supported": true,
      "citation_ids": ["chunk-17"]
    }]
  }]
}
```

Run `python -m eval.answer_quality annotations.json [--output report.json]`.
The aggregate includes expected-fact recall, unsupported-claim rate,
claim-level citation coverage, citation-ID validity against the provided
context IDs, and abstention accuracy. Empty denominators are reported as `null`.
The claim support label is the human's judgment; retain annotator identity,
adjudication notes, workload/corpus fingerprint, model/backend and prompt
revision alongside the input artifact when building a real evaluation set.

Do not label answer text generated from synthetic fixtures as factual quality
data. Start with a held-out workload spanning document QA, summarization,
long-context questions, multi-document retrieval, and negative controls. Include
blind double-annotation for a meaningful sample and adjudicate disagreements.
Keep retrieval metrics, answer-quality labels and serving latency joined by the
same workload-case ID, but report their denominators separately.

## Evaluation matrix and limits

For retrieval, compare full-corpus BM25 and dense retrieval first, then compare
rerankers using the same dense candidate pool. A later hybrid experiment should
freeze candidate generation, fusion method and candidate budget explicitly.
For answer quality, compare backends or quantizations on identical prompts,
retrieved contexts and decoding settings; pair performance (TTFT, total latency,
tokens/s, p95 and throughput) with these human labels. Record failed requests
and abstentions rather than dropping them from the denominator.

The local development scorer and BM25 run on CPU. Representative performance
and concurrency comparisons for vLLM/FP16/AWQ/GPTQ require a GPU host. Quality
annotation can be done locally, but reliable quality results require a larger,
held-out, reviewed dataset than the checked-in fixture. The current 40-case
workload and repeated serving measurements are reported separately; aggregate
groundedness remains pending human annotations.
