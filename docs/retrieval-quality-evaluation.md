# Retrieval and answer-quality evaluation

Phase 3 adds offline retrieval comparisons, answer capture, and an
annotation-driven answer scorer. These tools do not change DocChat's production
retriever; [hybrid retrieval](#hybrid-retrieval-bm25--rrf) is an opt-in production
mode that the retrieval comparison can now measure. Answer capture calls the
configured OpenAI-compatible local inference endpoint; the retrieval and scoring
tools run offline.

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

## Hybrid retrieval (BM25 + RRF)

Opt-in production mode, off by default (`RETRIEVAL_MODE=dense`). With
`RETRIEVAL_MODE=hybrid` the retriever asks Qdrant for two rankings in one
`/points/query/batch` round trip, a dense cosine search and a BM25 search over a
sparse `bm25` vector (fastembed `Qdrant/bm25`; IDF is applied by Qdrant over the
whole collection, so ingesting more sources never needs re-weighting), and fuses
them with reciprocal rank fusion (`app/services/hybrid.py`, `RETRIEVAL_RRF_K`,
default 60). The cosine floor (`RETRIEVAL_MIN_SCORE`) still applies to dense
candidates. A BM25-only candidate must score at least `RETRIEVAL_BM25_MIN_SCORE`
(default 0, i.e. any positive match) unless the dense ranking also passed it.
Fusion is done in the application rather than with Qdrant's server-side fusion so
`k` is configurable and the result does not depend on the Qdrant server version.

Degradation is automatic and lossless. A collection without the sparse field,
a BM25 model that fails to load, or a query with no indexable terms uses the
previous dense + overlap path (verified identical on the golden set). A Qdrant
error is not treated as "unsupported": it returns no chunks, as before.

### Enabling it on an existing index

Qdrant cannot add a sparse vector field to an existing collection, so enabling
hybrid retrieval copies the points into a new collection. Dense vectors and
payloads are copied as stored (no re-embedding); only the BM25 vectors are
computed. The source collection is never modified, so rollback is unsetting a
variable.

```sh
venv/bin/python -m scripts.migrate_to_hybrid_collection --dry-run
venv/bin/python -m scripts.migrate_to_hybrid_collection      # idempotent; re-run after quiescing ingestion
# then set, and restart the API and any MCP server:
#   QDRANT_SOURCE_COLLECTION=source_chunks_hybrid  RETRIEVAL_MODE=hybrid
```

New installs need no migration: ingestion creates the collection with the
sparse field. Ingestion into an old dense-only collection keeps working and
indexes dense-only, with a logged warning.

### What the measurements show

Production `retriever_node` against live Qdrant 1.18.1, the 24-question golden set
(17 chunks, two sources), first relevant chunk per question:

| Configuration | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|---:|---:|---:|---:|
| Dense + overlap rerank (default) | 0.792 | 0.979 | 1.000 | 0.958 |
| Hybrid BM25 + RRF | 0.708 | 1.000 | 1.000 | 0.903 |
| `hybrid` mode on a dense-only collection (fallback) | 0.792 | 0.979 | 1.000 | 0.958 |

The offline harness (`hybrid_rrf` arm, its own exact BM25) gives MRR 0.931 against
0.958 for the overlap reranker and 0.967 for BM25 alone; its other arms reproduce
the earlier report exactly. Six questions differ between the live arms, four worse
and two better, which is not evidence in either direction at this size.

Why RRF does not win here: the corpus is small and cosine scores are compressed
(roughly 0.69 to 0.74), so the overlap rerank's `0.75 * cosine + 0.25 * coverage`
lets strong keyword coverage override a small cosine gap, while RRF sees only
ranks. A chunk ranked first by BM25 and fifth by dense lands around third. RRF's
advantages (a candidate pool that includes exact-term matches the embedding
missed, no score calibration) matter when the corpus is large enough that the
relevant chunk is not already in the dense top candidates, which this set cannot
show.

Decision rule before changing the default: make hybrid the default only if it is
at least as good at Recall@1/MRR and better at Recall@5 on a larger held-out set.
That set has since been built (see "Larger set (v2)" below) and hybrid failed the
rule, so the default stays dense. The labels there are LLM-written and not
independently audited, and `RETRIEVAL_BM25_MIN_SCORE` is still untuned on
negative-control queries (BM25 returns something for almost any query and the
default gate admits it).

### Larger set (v2): hybrid is worse than the default, with confidence intervals

The decision rule above was run on a larger set: 127 questions over 781 chunks from 14 sources
(`eval/retrieval_golden_v2.json`, corpus snapshot `eval/retrieval_corpus_v2.json`; rebuild with
`python -m eval.build_retrieval_set_v2 corpus --from-snapshot`). The 24 original questions are kept and
sit among 764 new distractor chunks (12 Wikipedia pages: Okapi BM25, PostgreSQL, Kubernetes, TCP, Git,
Apollo 11, Marie Curie, Mount Everest, Photosynthesis, Great Barrier Reef, Black Death, Euro). The other 103
questions were written by an LLM from one sampled chunk each, alternating two strata: `exact_term` (hinges on a
name, number or term in the passage) and `paraphrase` (different words than the passage). Each needs a
verbatim evidence quote and must pass an answerable-from-the-chunk check; every chunk containing the quote is
labelled relevant, and questions whose quote appears in more than 3 chunks are dropped (12 candidates rejected
in total). Results come from `python -m eval.live_retrieval_ab` (the production `retriever_node`, both modes),
`python -m eval.retrieval_eval --golden-set eval/retrieval_golden_v2.json` and `python -m eval.retrieval_stats`
(paired bootstrap over questions, 10,000 resamples).

Production retriever, all 127 questions (reports: `reports/live_retrieval_ab_v2*.json`):

| Configuration | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|---:|---:|---:|---:|
| Dense + overlap rerank (default) | 0.693 | 0.862 | 0.890 | 0.834 |
| Hybrid BM25 + RRF | 0.583 | 0.823 | 0.850 | 0.761 |

Hybrid minus default: MRR **-0.073** (95% CI -0.114 to -0.035), Recall@1 **-0.110** (-0.173 to -0.051),
Recall@3 -0.039 (-0.087 to +0.004, not significant). Wins/losses/ties on MRR: 10/28/89. The loss shows in
every stratum: exact-term MRR 0.991 vs 0.923 (0 wins, 7 losses), paraphrase 0.602 vs 0.497, and the original
24 are within noise (0.958 vs 0.938, CI -0.104 to +0.062).

Offline harness (own exact BM25), all 127 questions:

| Arm | Recall@1 | Recall@3 | MRR |
|---|---:|---:|---:|
| Dense (cosine only) | 0.567 | 0.791 | 0.749 |
| BM25 only | 0.630 | 0.803 | 0.761 |
| Hybrid RRF | 0.594 | 0.862 | 0.781 |
| Cross-encoder (ms-marco MiniLM) | 0.665 | 0.827 | 0.813 |
| **Dense + overlap rerank (default)** | **0.693** | **0.870** | **0.835** |

What this says, with the intervals:
- **BM25 does help a plain dense search.** Hybrid RRF beats dense-only at Recall@3 (+0.071, CI +0.004 to +0.138)
  and MRR is up 0.032 (CI -0.017 to +0.080, not significant).
- **The default already captures most of that, and more.** `0.75 * cosine + 0.25 * query-term coverage` beats
  dense-only by +0.126 Recall@1 (CI +0.051 to +0.205) and beats hybrid RRF by 0.098 at Recall@1 (CI -0.165 to
  -0.035 for hybrid minus default). On exact-term questions the default has 0 losses to dense in 54 cases.
- The overlap reranker also scores above the cross-encoder (MRR 0.835 vs 0.813; that gap was not tested for significance), so a heavier reranker is not an obvious next step.
- The production and offline arms use different BM25 implementations and agree in direction and size.

**Decision: `RETRIEVAL_MODE` stays `dense`.** Hybrid fails the rule (not at least as good at Recall@1 and MRR).
Hybrid mode as built drops the overlap blend the default applies after retrieval. That is a plausible reason it
loses, but I did not isolate it. A variant that keeps the blend and uses BM25 only to widen the candidate pool is
untested and is the one hybrid design left worth an experiment.

Limits of this evidence: 103 of the 127 questions are LLM-written (Groq, with some calls falling back to
OpenAI) and not independently audited; I read a sample of 8 and they were sound, but some paraphrase questions
are vague enough that another chunk could answer them, which depresses every arm's absolute score on that
stratum (best MRR about 0.6). Exact-term questions share about 74% of their words with the gold chunk
(`lexical_overlap` in the file), so they flatter lexical methods and still did not rescue hybrid. All sources are
English Wikipedia plus the original two documents; no PDFs, code or non-English text. Corpus size (781 chunks) is
still small next to a real deployment. `RETRIEVAL_BM25_MIN_SCORE` was not tuned.

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
