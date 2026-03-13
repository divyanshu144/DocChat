"""Cross-encoder re-ranking via FlashRank (ONNX, no PyTorch required).

FlashRank downloads a ~50 MB ONNX model on first use.  If the package is not
installed the module degrades gracefully — retrieve_chunks results are passed
through unchanged.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

try:
    from flashrank import Ranker, RerankRequest
    _FLASHRANK_AVAILABLE = True
except ImportError:
    _FLASHRANK_AVAILABLE = False
    logger.warning("flashrank not installed — re-ranking disabled; run: pip install flashrank")

_ranker = None


def _get_ranker():
    global _ranker
    if _ranker is None and _FLASHRANK_AVAILABLE:
        _ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")
    return _ranker


async def rerank(query: str, chunks: list[str], top_k: int) -> list[str]:
    """Re-rank chunks by relevance to query; return the top_k highest-scoring ones.

    Runs in a thread-pool executor so it doesn't block the event loop.
    Falls back to returning chunks[:top_k] if FlashRank is unavailable.
    """
    ranker = _get_ranker()
    if ranker is None or not chunks:
        return chunks[:top_k]

    passages = [{"id": i, "text": c} for i, c in enumerate(chunks)]

    def _do_rerank() -> list[str]:
        request = RerankRequest(query=query, passages=passages)
        results = ranker.rerank(request)
        return [r["text"] for r in results[:top_k]]

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _do_rerank)
    except Exception:
        logger.exception("rerank_failed — falling back to unranked top_k")
        return chunks[:top_k]
