from app.agent.state import AgentState
from app.core.chroma import get_collection
from app.services.embedder import get_embedder

_SOURCE_COLLECTIONS = {
    "pdf": "pdf_chunks",
    "youtube": "youtube_chunks",
    "web": "web_chunks",
}
N_RESULTS = 5


async def retriever_node(state: AgentState) -> dict:
    embedder = get_embedder()
    if not embedder:
        return {"retrieved_chunks": []}

    query_emb = embedder.embed_query(state["query"]).tolist()
    all_chunks: list[dict] = []

    for source in state["sources_to_use"]:
        collection_name = _SOURCE_COLLECTIONS.get(source)
        if not collection_name:
            continue
        try:
            collection = get_collection(collection_name)
            results = collection.query(
                query_embeddings=[query_emb],
                n_results=N_RESULTS,
                include=["documents", "metadatas", "distances"],
            )
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                all_chunks.append({
                    "text": doc,
                    "metadata": meta,
                    "source_type": source,
                    "distance": dist,
                })
        except Exception:
            pass

    seen: set[str] = set()
    unique: list[dict] = []
    for chunk in all_chunks:
        if chunk["text"] not in seen:
            seen.add(chunk["text"])
            unique.append(chunk)

    return {"retrieved_chunks": unique}
