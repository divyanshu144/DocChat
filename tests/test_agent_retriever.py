import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from app.agent.state import AgentState
from app.agent.nodes.retriever import retriever_node


def _scored_point(text: str, score: float = 0.8, **payload_extra):
    sp = MagicMock()
    sp.score = score
    sp.payload = {"text": text, "filename": "doc.pdf", **payload_extra}
    return sp


def _base_state(**kwargs) -> AgentState:
    base: AgentState = {
        "query": "attention mechanisms",
        "conversation_id": "conv-1",
        "sources_to_use": ["pdf"],
        "source_ids": [],
        "retrieved_chunks": [],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
        "grounding_passed": False,
    }
    base.update(kwargs)
    return base


@pytest.mark.asyncio
async def test_retriever_queries_selected_sources():
    mock_client = MagicMock()
    mock_client.search.return_value = [_scored_point("chunk text", score=0.75)]
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever.get_qdrant_client", return_value=mock_client),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        result = await retriever_node(_base_state(sources_to_use=["pdf"]))

    assert len(result["retrieved_chunks"]) == 1
    assert result["retrieved_chunks"][0]["text"] == "chunk text"
    assert result["retrieved_chunks"][0]["source_type"] == "pdf"
    assert result["retrieved_chunks"][0]["score"] == 0.75


@pytest.mark.asyncio
async def test_retriever_deduplicates_chunks():
    mock_client = MagicMock()
    mock_client.search.return_value = [
        _scored_point("duplicate text", score=0.8),
        _scored_point("duplicate text", score=0.7),
    ]
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever.get_qdrant_client", return_value=mock_client),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        result = await retriever_node(_base_state(sources_to_use=["pdf"]))

    assert len(result["retrieved_chunks"]) == 1


@pytest.mark.asyncio
async def test_retriever_returns_empty_without_embedder():
    with patch("app.agent.nodes.retriever.get_embedder", return_value=None):
        result = await retriever_node(_base_state())

    assert result["retrieved_chunks"] == []


@pytest.mark.asyncio
async def test_retriever_applies_source_id_filter():
    mock_client = MagicMock()
    mock_client.search.return_value = [_scored_point("filtered chunk")]
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever.get_qdrant_client", return_value=mock_client),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        await retriever_node(_base_state(sources_to_use=["pdf"], source_ids=["src-123"]))

    call_kwargs = mock_client.search.call_args.kwargs
    assert call_kwargs["query_filter"] is not None
