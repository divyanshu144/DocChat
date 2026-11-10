"""Rank fusion for hybrid (dense + BM25) retrieval. Pure functions, no I/O."""
from __future__ import annotations

from collections.abc import Hashable, Sequence


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[Hashable]],
    k: int = 60,
    weights: Sequence[float] | None = None,
) -> list[tuple[Hashable, float]]:
    """Fuse ranked id lists with reciprocal rank fusion (Cormack, Clarke & Buettcher, SIGIR 2009).

    ``score(d) = sum_r weight_r / (k + rank_r(d))`` with 1-based ranks. Only ranks are used, so a cosine
    similarity and a BM25 score never need calibrating against each other. ``k`` damps the head of each list;
    60 is the value from the paper and the default in Elasticsearch, OpenSearch and Qdrant.

    An id repeated inside one ranking counts once, at its best position. Ties break by the best rank the id
    achieved in any list, then by first appearance, so the output is deterministic.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    if weights is not None and len(weights) != len(rankings):
        raise ValueError("weights must match the number of rankings")
    weights = weights if weights is not None else [1.0] * len(rankings)

    scores: dict[Hashable, float] = {}
    best_rank: dict[Hashable, int] = {}
    first_seen: dict[Hashable, int] = {}
    for weight, ranking in zip(weights, rankings, strict=True):
        seen_in_list: set[Hashable] = set()
        position = 0
        for item in ranking:
            if item in seen_in_list:
                continue
            seen_in_list.add(item)
            position += 1
            scores[item] = scores.get(item, 0.0) + weight / (k + position)
            best_rank[item] = min(best_rank.get(item, position), position)
            first_seen.setdefault(item, len(first_seen))
    ordered = sorted(scores, key=lambda item: (-scores[item], best_rank[item], first_seen[item]))
    return [(item, scores[item]) for item in ordered]
