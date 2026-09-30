import logging
import re
import httpx
from qdrant_client.models import Filter, FieldCondition, MatchAny
from app.agent.state import AgentState
from app.core.config import settings
from app.core.sources import source_collection
from app.services.embedder import get_embedder

logger = logging.getLogger(__name__)

N_RESULTS_PER_SOURCE = 8
MAX_RERANKED_CHUNKS = 12

_QDRANT_BASE = f"http://{settings.qdrant_host}:{settings.qdrant_port}"


async def _search(collection_name: str, query_vector: list, limit: int, qdrant_filter=None) -> list:
    payload: dict = {"vector": query_vector, "limit": limit, "with_payload": True}
    if qdrant_filter is not None:
        payload["filter"] = qdrant_filter.model_dump(mode="json", exclude_none=True)
    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.post(
            f"{_QDRANT_BASE}/collections/{collection_name}/points/search",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["result"]


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


async def retriever_node(state: AgentState) -> dict:
    embedder = get_embedder()
    if not embedder:
        logger.error("retriever: embedder is None — fastembed failed to load")
        return {"retrieved_chunks": []}

    query_emb = embedder.embed_query(state["query"]).tolist()
    source_ids = state.get("source_ids") or []
    source_types = state.get("sources_to_use") or []
    qdrant_filter = _retrieval_filter(source_types, source_ids)

    logger.debug("[RETRIEVER] query=%r sources=%s source_ids=%s", state["query"], source_types, source_ids)

    all_chunks: list[dict] = []
    try:
        hits = await _search(
            source_collection(),
            query_emb,
            max(N_RESULTS_PER_SOURCE * max(len(source_types), 1), MAX_RERANKED_CHUNKS),
            qdrant_filter,
        )
        logger.debug("[RETRIEVER] %s -> %d hits", source_collection(), len(hits))
        for hit in hits:
            payload = dict(hit.get("payload") or {})
            source_type = payload.get("source_type") or "unknown"
            all_chunks.append({
                "text": payload.pop("text", ""),
                "metadata": payload,
                "source_type": source_type,
                "score": hit.get("score", 0.0),
            })
    except Exception as exc:
        logger.exception("[RETRIEVER ERROR] collection=%s error=%s", source_collection(), exc)

    seen: set[str] = set()
    unique: list[dict] = []
    for chunk in all_chunks:
        if chunk["text"] not in seen:
            seen.add(chunk["text"])
            unique.append(chunk)

    return {"retrieved_chunks": _rerank(state["query"], unique)}
