import logging
import httpx
from qdrant_client.models import Filter, FieldCondition, MatchAny
from app.agent.state import AgentState
from app.core.config import settings
from app.services.embedder import get_embedder

logger = logging.getLogger(__name__)

_SOURCE_COLLECTIONS = {
    "pdf": "pdf_chunks",
    "youtube": "youtube_chunks",
    "web": "web_chunks",
}
N_RESULTS = 8

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


async def retriever_node(state: AgentState) -> dict:
    embedder = get_embedder()
    if not embedder:
        logger.error("retriever: embedder is None — fastembed failed to load")
        return {"retrieved_chunks": []}

    query_emb = embedder.embed_query(state["query"]).tolist()
    source_ids = state.get("source_ids") or []

    qdrant_filter = (
        Filter(must=[FieldCondition(key="source_id", match=MatchAny(any=source_ids))])
        if source_ids
        else None
    )

    logger.debug("[RETRIEVER] query=%r sources=%s source_ids=%s", state["query"], state["sources_to_use"], source_ids)

    all_chunks: list[dict] = []
    for source in state["sources_to_use"]:
        collection_name = _SOURCE_COLLECTIONS.get(source)
        if not collection_name:
            continue
        try:
            hits = await _search(collection_name, query_emb, N_RESULTS, qdrant_filter)
            logger.debug("[RETRIEVER] %s → %d hits", collection_name, len(hits))
            for hit in hits:
                payload = dict(hit.get("payload") or {})
                all_chunks.append({
                    "text": payload.pop("text", ""),
                    "metadata": payload,
                    "source_type": source,
                    "score": hit.get("score", 0.0),
                })
        except Exception as exc:
            logger.exception("[RETRIEVER ERROR] collection=%s error=%s", collection_name, exc)

    seen: set[str] = set()
    unique: list[dict] = []
    for chunk in all_chunks:
        if chunk["text"] not in seen:
            seen.add(chunk["text"])
            unique.append(chunk)

    return {"retrieved_chunks": unique}
