"""Score the *production* retriever node in dense (+overlap) mode and in hybrid (BM25 + RRF) mode.

`eval.retrieval_eval` ranks with its own dependency-free BM25; the flag that matters is whether
`RETRIEVAL_MODE=hybrid` beats the default on the code that actually serves queries, so this runs
`retriever_node` itself against a live Qdrant collection (Qdrant's BM25 with IDF, fastembed query encoder,
client-side RRF). No LLM calls. The report has the same shape as `retrieval_eval` so `eval.retrieval_stats`
can compare the two arms.

  QDRANT_SOURCE_COLLECTION=eval_corpus_v2 python -m eval.live_retrieval_ab --golden-set eval/retrieval_golden_v2.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from eval.retrieval_eval import recall_at_k, reciprocal_rank

ROOT = Path(__file__).resolve().parent.parent
ARMS = {"prod_dense": "dense", "prod_hybrid": "hybrid"}


def ids_for_chunks(chunks: list[dict], ids_by_text: dict[str, list[str]], relevant: set[str]) -> list[str]:
    """Map returned chunk texts back to point ids (the node returns text, not ids). A text shared by several points
    resolves to a relevant one when there is one, so duplicated boilerplate is never counted against an arm."""
    ranked: list[str] = []
    for chunk in chunks:
        candidates = ids_by_text.get(chunk["text"], [])
        if not candidates:
            ranked.append(f"unmapped:{len(ranked)}")
            continue
        ranked.append(next((c for c in candidates if c in relevant), candidates[0]))
    return ranked


def ranking_row(ids: list[str], relevant: list[str]) -> dict:
    return {"ids": ids, "reciprocal_rank": reciprocal_rank(ids, relevant),
            **{f"recall@{k}": recall_at_k(ids, relevant, k) for k in (1, 3, 5)}}


async def run(golden: Path, limit: int | None) -> dict:
    from app.agent.nodes import retriever
    from app.core.config import settings
    from app.core.qdrant import collection_has_sparse, get_qdrant_client
    from app.core.sources import source_collection

    collection = source_collection()
    if not collection_has_sparse(collection):
        raise SystemExit(f"'{collection}' has no BM25 vector; hybrid would silently fall back to dense.")
    client = get_qdrant_client()
    ids_by_text: dict[str, list[str]] = {}
    offset = None
    while True:
        points, offset = client.scroll(collection, limit=200, offset=offset, with_payload=["text"], with_vectors=False)
        for point in points:
            ids_by_text.setdefault(point.payload["text"], []).append(str(point.id))
        if offset is None:
            break

    cases = json.loads(golden.read_text())["cases"][:limit]
    rows = []
    for case in cases:
        relevant = set(case["relevant_ids"])
        row = {"id": case["id"], "query": case["query"], "relevant_ids": case["relevant_ids"],
               "stratum": case.get("stratum"), "lexical_overlap": case.get("lexical_overlap"), "rankings": {}}
        for arm, mode in ARMS.items():
            settings.retrieval_mode = mode
            retriever._hybrid_unsupported_since.clear()
            state = {"query": case["query"], "conversation_id": "ab", "conversation_history": [],
                     "sources_to_use": [], "source_ids": [], "retrieved_chunks": []}
            out = await retriever.retriever_node(state)
            row["rankings"][arm] = ranking_row(ids_for_chunks(out["retrieved_chunks"], ids_by_text, relevant),
                                               case["relevant_ids"])
        rows.append(row)
    await retriever.close_retriever_client()
    summary = {arm: {m: statistics.fmean(r["rankings"][arm][m] for r in rows)
                     for m in ("reciprocal_rank", "recall@1", "recall@3", "recall@5")} for arm in ARMS}
    return {"summary": summary, "results": rows, "generated_at": datetime.now(timezone.utc).isoformat(),
            "collection": collection, "corpus_chunks": sum(len(v) for v in ids_by_text.values()),
            "cases": len(rows), "method": "production retriever_node in dense and hybrid modes"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden-set", type=Path, default=ROOT / "eval/retrieval_golden_v2.json")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/live_retrieval_ab.json")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    report = asyncio.run(run(args.golden_set, args.limit))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
