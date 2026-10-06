# Historical retrieval comparison, 2026-10-01

These numbers predate the Phase 3 independent BM25 baseline. “Current lexical
rerank” below is the production overlap reranker applied to dense candidates; it
is not BM25. See [the Phase 3 evaluation guide](../docs/retrieval-quality-evaluation.md)
for the new experiment definitions. Do not compare these historical numbers to a
new BM25 run without checking its corpus fingerprint and candidate protocol.

Read-only evaluation of the existing `source_chunks` index: 17 chunks from one
uploaded working-time declaration and the ingested Wikipedia RAG article. The
[golden set](../eval/retrieval_golden.json) contains 24 questions with chunk-level
labels and evidence excerpts. [Raw results](retrieval_eval.json) contain all rankings,
per-question metrics, model names and the corpus SHA-256 fingerprint.

| Ranking | Recall@1 | Recall@3 | Recall@5 | MRR@12 | Mean ranking time |
|---|---:|---:|---:|---:|---:|
| Dense cosine | 0.7292 | 0.8750 | 0.9583 | 0.9111 | 0.13 ms |
| Current lexical rerank | 0.7917 | 0.9792 | 1.0000 | 0.9583 | 0.14 ms |
| CPU cross-encoder | 0.8542 | 1.0000 | 1.0000 | 1.0000 | 1174.46 ms |

The lexical rerank improved this small corpus at negligible ranking cost. The
cross-encoder placed at least one labeled relevant chunk first for every question,
but added about 1.17 seconds per query on this machine. Recall@1 is lower than MRR
because multi-chunk questions can have more than one relevant chunk. These findings
do not justify a production ranker change; production remains dense plus lexical.

## Method

Use the existing stored vectors and `BAAI/bge-small-en-v1.5` query embeddings on CPU.
Calculate exact cosine similarity over the complete small corpus, take up to 24
candidates and apply the production cosine floor of 0.3. All methods receive the
same filtered candidate pool, then retain at most 12 results. Lexical ranking calls
the production `_rerank` function. Experimental reranking uses the fastembed ONNX
`Xenova/ms-marco-MiniLM-L-6-v2` cross-encoder, CPU provider and two threads.

This is an exact-search ranking experiment on real indexed content, not a Qdrant
ANN or network benchmark. Timing excludes query embedding, downloading/model startup
and network. Cross-encoder timing includes tokenization and inference. It does not
measure end-to-end pipeline latency or generated-answer quality.

Reproduce against the unchanged local index:

```bash
venv/bin/python -m eval.retrieval_eval --qdrant-url http://localhost:6333 \
  --embedding-cache-dir "$HOME/.cache/fastembed"
```

The evaluator refuses missing or changed labeled evidence. The first run may
download the CPU models; it makes no paid LLM calls and creates no GPU pod. For an
offline reproduction, supply a Qdrant scroll JSON export with vectors using
`--corpus-file`. The temporary original export is not added to the repository.

## Limits

Two documents and 24 source-derived queries are a small, optimistic development
set. One annotator inspected chunks and assigned relevance; no independent labeling
or held-out corpus was used. Similar topic variants are correlated. Reference-only
chunks are not labeled relevant unless they answer the query. Document statements
are evaluated as indexed text, not as verified legal or factual advice.

Before deployment decisions, independently audit labels, add held-out documents,
include harder negatives and ambiguous queries, measure candidate recall at larger
corpus sizes, and repeat timing under representative traffic. No production retrieval
behavior was changed based on these results.
