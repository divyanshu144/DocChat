import asyncio
import logging
import re
import time
from weakref import WeakKeyDictionary
import httpx
from qdrant_client.models import Filter, FieldCondition, MatchAny
from app.agent.state import AgentState
from app.core.config import settings
from app.core.telemetry import span, annotate
from app.core.qdrant import SPARSE_VECTOR_NAME, qdrant_headers
from app.core.sources import source_collection
from app.services.embedder import SparseVec, get_embedder
from app.services.hybrid import reciprocal_rank_fusion

logger = logging.getLogger(__name__)

N_RESULTS_PER_SOURCE = 8
MAX_RERANKED_CHUNKS = 12

_http_clients: WeakKeyDictionary = WeakKeyDictionary()


def _get_http_client() -> httpx.AsyncClient:
    # Connection pools belong to the loop that uses them (API, MCP, or eval).
    loop = asyncio.get_running_loop()
    client = _http_clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=30.0)
        _http_clients[loop] = client
    return client


async def close_retriever_client() -> None:
    client = _http_clients.pop(asyncio.get_running_loop(), None)
    if client is not None:
        await client.aclose()


async def _search(collection_name: str, query_vector: list, limit: int, qdrant_filter=None) -> list:
    payload: dict = {"vector": query_vector, "limit": limit, "with_payload": True}
    if qdrant_filter is not None:
        payload["filter"] = qdrant_filter.model_dump(mode="json", exclude_none=True)
    base_url = f"http://{settings.qdrant_host}:{settings.qdrant_port}"
    resp = await _get_http_client().post(
        f"{base_url}/collections/{collection_name}/points/search",
        json=payload,
        headers=qdrant_headers(),
    )
    resp.raise_for_status()
    return resp.json()["result"]


class HybridUnsupported(Exception):
    """The collection has no BM25 vector field (it predates hybrid retrieval)."""


# Collections found to lack the sparse field are not re-probed on every query, but are re-checked after this
# many seconds so a finished migration (or a recreated collection) is picked up without a restart.
_HYBRID_RECHECK_S = 60.0
_hybrid_unsupported_since: dict[str, float] = {}


def _hybrid_known_unsupported(collection: str) -> bool:
    marked = _hybrid_unsupported_since.get(collection)
    if marked is None:
        return False
    if time.monotonic() - marked > _HYBRID_RECHECK_S:
        del _hybrid_unsupported_since[collection]
        return False
    return True


async def _hybrid_search(
    collection_name: str, dense_vector: list, sparse: SparseVec, limit: int, qdrant_filter=None
) -> tuple[list, list]:
    """Dense and BM25 candidates in one Qdrant round trip (same snapshot), each best-first."""
    common: dict = {"limit": limit, "with_payload": True}
    if qdrant_filter is not None:
        common["filter"] = qdrant_filter.model_dump(mode="json", exclude_none=True)
    searches = [
        {"query": dense_vector, **common},
        {"query": {"indices": sparse.indices, "values": sparse.values}, "using": SPARSE_VECTOR_NAME, **common},
    ]
    base_url = f"http://{settings.qdrant_host}:{settings.qdrant_port}"
    resp = await _get_http_client().post(
        f"{base_url}/collections/{collection_name}/points/query/batch",
        json={"searches": searches},
        headers=qdrant_headers(),
    )
    if resp.status_code == 400 and "vector name" in resp.text.lower():
        raise HybridUnsupported(collection_name)
    resp.raise_for_status()
    dense_result, sparse_result = resp.json()["result"]
    return dense_result["points"], sparse_result["points"]


def _chunk_from_hit(hit: dict, score: float) -> dict:
    payload = dict(hit.get("payload") or {})
    return {
        "text": payload.pop("text", ""),
        "metadata": payload,
        "source_type": payload.get("source_type") or "unknown",
        "score": score,
    }


def admit_hybrid_candidates(
    dense_hits: list[dict], sparse_hits: list[dict], *, min_score: float, bm25_min_score: float
) -> tuple[list[dict], list[dict]]:
    """Apply the candidate gates to each ranking (order preserved).

    Dense candidates keep the cosine floor (``min_score``) that guards against answering from unrelated text.
    A BM25 candidate is admitted when it also passed the dense floor, or when it scores at least
    ``bm25_min_score``: a rare exact term (an error code, a clause number) can matter even when the embedding
    does not see it.
    """
    dense = [hit for hit in dense_hits if hit.get("score", 0.0) >= min_score]
    dense_ids = {hit["id"] for hit in dense}
    sparse = [
        hit for hit in sparse_hits
        if hit.get("score", 0.0) > 0 and (hit["id"] in dense_ids or hit["score"] >= bm25_min_score)
    ]
    return dense, sparse


def fuse_hybrid(
    dense_hits: list[dict],
    sparse_hits: list[dict],
    *,
    min_score: float,
    bm25_min_score: float,
    rrf_k: int,
    limit: int,
) -> list[dict]:
    """Reciprocal-rank-fuse dense and BM25 candidates into the chunks handed to the synthesizer.

    The returned ``score`` is the RRF score, not a cosine similarity.
    """
    dense, sparse = admit_hybrid_candidates(
        dense_hits, sparse_hits, min_score=min_score, bm25_min_score=bm25_min_score
    )
    hits_by_id = {hit["id"]: hit for hit in [*sparse, *dense]}
    fused = reciprocal_rank_fusion([[h["id"] for h in dense], [h["id"] for h in sparse]], k=rrf_k)

    chunks: list[dict] = []
    seen_text: set[str] = set()
    for point_id, score in fused:
        chunk = _chunk_from_hit(hits_by_id[point_id], score)
        if chunk["text"] in seen_text:
            continue
        seen_text.add(chunk["text"])
        chunks.append(chunk)
        if len(chunks) >= limit:
            break
    return chunks


def _query_terms(query: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", query.lower())
        if term not in {"the", "and", "for", "with", "what", "how", "which"}
    }


def _rerank(query: str, chunks: list[dict], limit: int = MAX_RERANKED_CHUNKS) -> list[dict]:
    terms = _query_terms(query)
    if not terms:
        return sorted(chunks, key=lambda c: c.get("score", 0.0), reverse=True)[:limit]

    def score(chunk: dict) -> float:
        text = chunk.get("text", "").lower()
        overlap = sum(1 for term in terms if term in text)
        lexical = overlap / len(terms)
        return (0.75 * float(chunk.get("score", 0.0))) + (0.25 * lexical)

    return sorted(chunks, key=score, reverse=True)[:limit]


def _retrieval_filter(source_types: list[str], source_ids: list[str]):
    must = []
    if source_types and not source_ids:
        must.append(FieldCondition(key="source_type", match=MatchAny(any=source_types)))
    if source_ids:
        must.append(FieldCondition(key="source_id", match=MatchAny(any=source_ids)))
    return Filter(must=must) if must else None


async def _dense_candidates(collection: str, query_emb: list, source_types: list[str], qdrant_filter) -> list[dict]:
    """Dense-only candidates above the cosine floor (the behaviour before hybrid retrieval)."""
    hits = await _search(
        collection,
        query_emb,
        max(N_RESULTS_PER_SOURCE * max(len(source_types), 1), MAX_RERANKED_CHUNKS),
        qdrant_filter,
    )
    logger.debug("[RETRIEVER] %s -> %d hits", collection, len(hits))
    chunks: list[dict] = []
    dropped_low_score = 0
    for hit in hits:
        score = hit.get("score", 0.0)
        if score < settings.retrieval_min_score:
            dropped_low_score += 1
            continue
        chunks.append(_chunk_from_hit(hit, score))
    if dropped_low_score:
        logger.debug(
            "[RETRIEVER] dropped %d/%d hits below retrieval_min_score=%.2f",
            dropped_low_score, len(hits), settings.retrieval_min_score,
        )
    return chunks


def _dedupe_by_text(chunks: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for chunk in chunks:
        if chunk["text"] not in seen:
            seen.add(chunk["text"])
            unique.append(chunk)
    return unique


async def retriever_node(state: AgentState) -> dict:
    with span("retrieval.embedding_init"):
        embedder = await asyncio.to_thread(get_embedder)
    if not embedder:
        annotate(retrieval_failed=True, retrieved_chunks_count=0)
        logger.error("retriever: embedder is None — fastembed failed to load")
        return {"retrieved_chunks": []}

    collection = source_collection()
    want_hybrid = settings.retrieval_mode == "hybrid" and not _hybrid_known_unsupported(collection)
    with span("retrieval.embedding"):
        query_emb = (await asyncio.to_thread(embedder.embed_query, state["query"])).tolist()
        sparse_query = None
        if want_hybrid:
            sparse_query = await asyncio.to_thread(embedder.embed_sparse_query, state["query"])
            if not isinstance(sparse_query, SparseVec) or not sparse_query.indices:
                # No BM25 model, or a query with no indexable terms (all stopwords): dense handles it alone.
                sparse_query = None
    source_ids = state.get("source_ids") or []
    source_types = state.get("sources_to_use") or []
    qdrant_filter = _retrieval_filter(source_types, source_ids)

    logger.debug("[RETRIEVER] query=%r sources=%s source_ids=%s", state["query"], source_types, source_ids)

    ranked: list[dict] = []
    mode = "dense"
    try:
        with span("retrieval.search") as search_span:
            if sparse_query is not None:
                try:
                    dense_hits, sparse_hits = await _hybrid_search(
                        collection, query_emb, sparse_query, settings.retrieval_candidates, qdrant_filter
                    )
                except HybridUnsupported:
                    _hybrid_unsupported_since[collection] = time.monotonic()
                    logger.warning(
                        "[RETRIEVER] collection %s has no %s field; using dense retrieval. Run "
                        "scripts/migrate_to_hybrid_collection.py to enable hybrid retrieval.",
                        collection, SPARSE_VECTOR_NAME,
                    )
                else:
                    mode = "hybrid"
                    search_span.update(dense_candidates=len(dense_hits), bm25_candidates=len(sparse_hits))
            search_span["retrieval_mode"] = mode
            if mode == "dense":
                candidates = await _dense_candidates(collection, query_emb, source_types, qdrant_filter)
        with span("retrieval.reranking", mode=mode):
            if mode == "hybrid":
                ranked = fuse_hybrid(
                    dense_hits, sparse_hits,
                    min_score=settings.retrieval_min_score,
                    bm25_min_score=settings.retrieval_bm25_min_score,
                    rrf_k=settings.retrieval_rrf_k,
                    limit=MAX_RERANKED_CHUNKS,
                )
            else:
                unique = _dedupe_by_text(candidates)
                annotate(candidates=len(unique))
                ranked = _rerank(state["query"], unique)
    except Exception as exc:
        annotate(retrieval_failed=True)
        logger.exception("[RETRIEVER ERROR] collection=%s error=%s", collection, exc)
        ranked = []

    annotate(retrieved_chunks_count=len(ranked), retrieval_mode=mode)
    return {"retrieved_chunks": ranked}
