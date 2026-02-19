from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk


async def retrieve_chunks(query: str, document_id: str, db: AsyncSession, top_k: int) -> list[str]:
    """Return the top-k most relevant chunk texts for a query using BM25."""
    result = await db.execute(
        select(Chunk)
        .where(Chunk.document_id == document_id)
        .order_by(Chunk.chunk_index)
    )
    chunks = result.scalars().all()

    if not chunks:
        return []

    tokenized_corpus = [chunk.text.lower().split() for chunk in chunks]
    bm25 = BM25Okapi(tokenized_corpus)

    tokenized_query = query.lower().split()
    scores = bm25.get_scores(tokenized_query)

    ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
    return [chunk.text for _, chunk in ranked[:top_k]]
