"""Read-only ranking evaluation against a labeled, real Qdrant corpus.

No LLM calls. Cross-encoder inference runs on CPU, separately from production.
Use --corpus-file for an exported Qdrant scroll response to reproduce rankings
offline (vectors required); otherwise connect to the existing local collection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
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
        lexical = _rerank(case["query"], candidates)
        lexical_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        rerank_scores = list(cross_encoder.rerank(case["query"], [row["text"] for row in candidates])) if candidates else []
        cross = [row for _, row in sorted(
            zip(rerank_scores, candidates, strict=True), key=lambda pair: pair[0], reverse=True
        )][:12]
        cross_ms = (time.perf_counter() - started) * 1000
        rankings = {"dense": candidates[:12], "lexical": lexical, "cross_encoder": cross}
        row = {"id": case["id"], "query": case["query"], "relevant_ids": case["relevant_ids"],
               "candidate_count": len(candidates), "timing_ms": {
                   "dense": dense_ms, "lexical": lexical_ms, "cross_encoder": cross_ms}, "rankings": {}}
        for method, ranked in rankings.items():
            ids = [hit["id"] for hit in ranked]
            row["rankings"][method] = {"ids": ids, "reciprocal_rank": reciprocal_rank(ids, case["relevant_ids"]),
                                      **{f"recall@{k}": recall_at_k(ids, case["relevant_ids"], k) for k in (1, 3, 5)}}
        results.append(row)
    summary = {}
    for method in ("dense", "lexical", "cross_encoder"):
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
                  method="Exact CPU cosine search over existing stored vectors; shared dense candidate pool",
                  caveats=["Small two-source corpus; not a production generalization claim",
                           "Labels written from source chunks; no independent annotator",
                           "Ranking times exclude query embedding and network; no latency deployment claim",
                           "MRR is truncated to 12 results; recall labels include all identified relevant chunks"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
