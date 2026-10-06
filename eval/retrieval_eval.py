"""Read-only ranking evaluation against a labeled, real Qdrant corpus.

No LLM calls. Cross-encoder inference runs on CPU, separately from production.
Use --corpus-file for an exported Qdrant scroll response to reproduce rankings
offline (vectors required); otherwise connect to the existing local collection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.agent.nodes.retriever import _rerank
from app.core.config import settings
from app.core.sources import source_collection

ROOT = Path(__file__).resolve().parent.parent


def recall_at_k(ranked_ids: list[str], relevant_ids: list[str], k: int) -> float:
    relevant = set(relevant_ids)
    if not relevant or k < 1:
        return 0.0
    return len(set(ranked_ids[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked_ids: list[str], relevant_ids: list[str]) -> float:
    relevant = set(relevant_ids)
    for rank, point_id in enumerate(ranked_ids, 1):
        if point_id in relevant:
            return 1.0 / rank
    return 0.0


_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['’][a-z0-9]+)?", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(text)]


def bm25_scores(query: str, documents: list[str], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Return BM25 scores for a query over the complete supplied corpus."""
    if not documents:
        return []
    if k1 <= 0 or not 0 <= b <= 1:
        raise ValueError("BM25 requires k1 > 0 and 0 <= b <= 1")
    tokenized = [_tokens(document) for document in documents]
    query_terms = Counter(_tokens(query))
    lengths = [len(document) for document in tokenized]
    average_length = sum(lengths) / len(lengths) or 1.0
    frequencies = [Counter(document) for document in tokenized]
    document_frequency = Counter(term for counts in frequencies for term in counts)
    count = len(documents)
    scores = [0.0] * count
    for term, query_frequency in query_terms.items():
        df = document_frequency[term]
        inverse_frequency = max(0.0, math.log(1 + (count - df + 0.5) / (df + 0.5)))
        for index, term_counts in enumerate(frequencies):
            term_frequency = term_counts[term]
            if term_frequency:
                length_norm = 1 - b + b * lengths[index] / average_length
                scores[index] += query_frequency * inverse_frequency * (
                    term_frequency * (k1 + 1) / (term_frequency + k1 * length_norm)
                )
    return scores


def load_cases(path: Path, corpus: list[dict]) -> list[dict]:
    cases = json.loads(path.read_text())["cases"]
    if not 20 <= len(cases) <= 30:
        raise ValueError("Golden set must have 20–30 questions")
    points = {str(point["id"]): point["payload"] for point in corpus}
    for case in cases:
        if not case["relevant_ids"]:
            raise ValueError(f"{case['id']}: missing relevant chunks")
        for point_id in case["relevant_ids"]:
            if point_id not in points:
                raise ValueError(f"{case['id']}: labeled chunk missing; rebuild labels for this corpus")
        for evidence in case["evidence"]:
            if evidence["quote"] not in points[evidence["point_id"]]["text"]:
                raise ValueError(f"{case['id']}: evidence text changed; relabel before comparing")
    return cases


def corpus_digest(corpus: list[dict]) -> str:
    rows = sorted((str(p["id"]), p["payload"]["text"]) for p in corpus)
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def evaluate(corpus: list[dict], cases: list[dict], embedder, cross_encoder, *, candidate_limit: int = 24) -> dict:
    import numpy as np

    vectors = np.asarray([point["vector"] for point in corpus], dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1)
    if np.any(norms == 0):
        raise ValueError("Corpus includes zero vectors")
    vectors /= norms[:, None]
    queries = list(embedder.embed([case["query"] for case in cases]))
    results = []
    for case, vector in zip(cases, queries, strict=True):
        started = time.perf_counter()
        vector = np.asarray(vector, dtype=np.float32)
        scores = vectors @ (vector / np.linalg.norm(vector))
        ordered = np.argsort(-scores, kind="stable")[:candidate_limit]
        candidates = [
            {"id": str(corpus[index]["id"]), "text": corpus[index]["payload"]["text"],
             "score": float(scores[index])}
            for index in ordered if scores[index] >= settings.retrieval_min_score
        ]
        dense_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        dense_overlap = _rerank(case["query"], candidates)
        lexical_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        rerank_scores = list(cross_encoder.rerank(case["query"], [row["text"] for row in candidates])) if candidates else []
        cross = [row for _, row in sorted(
            zip(rerank_scores, candidates, strict=True), key=lambda pair: pair[0], reverse=True
        )][:12]
        cross_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        bm25_values = bm25_scores(case["query"], [point["payload"]["text"] for point in corpus])
        bm25_order = sorted(range(len(corpus)), key=lambda index: (-bm25_values[index], index))
        bm25 = [
            {"id": str(corpus[index]["id"]), "text": corpus[index]["payload"]["text"],
             "score": bm25_values[index]}
            for index in bm25_order[:12] if bm25_values[index] > 0
        ]
        bm25_ms = (time.perf_counter() - started) * 1000
        rankings = {"dense": candidates[:12], "bm25": bm25, "dense_overlap_rerank": dense_overlap,
                    "cross_encoder": cross}
        row = {"id": case["id"], "query": case["query"], "relevant_ids": case["relevant_ids"],
               "candidate_count": len(candidates), "bm25_corpus_count": len(corpus), "timing_ms": {
                   "dense": dense_ms, "bm25": bm25_ms, "dense_overlap_rerank": lexical_ms,
                   "cross_encoder": cross_ms}, "rankings": {}}
        for method, ranked in rankings.items():
            ids = [hit["id"] for hit in ranked]
            row["rankings"][method] = {"ids": ids, "reciprocal_rank": reciprocal_rank(ids, case["relevant_ids"]),
                                      **{f"recall@{k}": recall_at_k(ids, case["relevant_ids"], k) for k in (1, 3, 5)}}
        results.append(row)
    summary = {}
    for method in ("dense", "bm25", "dense_overlap_rerank", "cross_encoder"):
        summary[method] = {metric: statistics.mean(row["rankings"][method][metric] for row in results)
                           for metric in ("recall@1", "recall@3", "recall@5", "reciprocal_rank")}
        summary[method]["mean_ranking_ms"] = statistics.mean(row["timing_ms"][method] for row in results)
    return {"summary": summary, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qdrant-url", default=f"http://{settings.qdrant_host}:{settings.qdrant_port}")
    parser.add_argument("--corpus-file", type=Path)
    parser.add_argument("--golden-set", type=Path, default=ROOT / "eval/retrieval_golden.json")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/retrieval_eval.json")
    parser.add_argument("--cache-dir", type=Path, default=Path("/private/tmp/docchat-retrieval-models"))
    parser.add_argument("--embedding-cache-dir", type=Path, default=None)
    args = parser.parse_args()
    if args.corpus_file:
        corpus = json.loads(args.corpus_file.read_text())["result"]["points"]
    else:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=args.qdrant_url, timeout=10)
        corpus = []
        offset = None
        try:
            while True:
                points, offset = client.scroll(source_collection(), limit=100, offset=offset,
                                               with_payload=True, with_vectors=True)
                corpus.extend(point.model_dump() for point in points)
                if offset is None:
                    break
        finally:
            client.close()
    if not corpus:
        raise SystemExit("Index is empty. Ask which documents to use before labeling or running an eval.")
    cases = load_cases(args.golden_set, corpus)
    from fastembed import TextEmbedding
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    model = "Xenova/ms-marco-MiniLM-L-6-v2"
    embedder = TextEmbedding(model_name=settings.embedding_model,
                             cache_dir=str(args.embedding_cache_dir or args.cache_dir), threads=2,
                             providers=["CPUExecutionProvider"])
    cross_encoder = TextCrossEncoder(model_name=model, cache_dir=str(args.cache_dir), threads=2,
                                    providers=["CPUExecutionProvider"])
    report = evaluate(corpus, cases, embedder, cross_encoder)
    report.update(generated_at=datetime.now(timezone.utc).isoformat(), corpus_sha256=corpus_digest(corpus),
                  corpus_chunks=len(corpus), source_ids=sorted({p["payload"]["source_id"] for p in corpus}),
                  embedding_model=settings.embedding_model, cross_encoder=model,
                  candidate_limit=24, min_score=settings.retrieval_min_score, ranking_limit=12,
                  method="Exact CPU dense cosine and full-corpus BM25; overlap and cross-encoder rerank the dense candidate pool",
                  caveats=["Small two-source corpus; not a production generalization claim",
                           "Labels written from source chunks; no independent annotator",
                           "Ranking times exclude query embedding and network; no latency deployment claim",
                           "BM25 uses a dependency-free tokenizer and full corpus; BM25 results are not the production ranker",
                           "MRR is truncated to 12 results; recall labels include all identified relevant chunks"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
