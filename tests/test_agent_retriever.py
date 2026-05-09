import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from app.agent.state import AgentState
from app.agent.nodes.retriever import retriever_node


def _base_state(**kwargs) -> AgentState:
    base: AgentState = {
        "query": "attention mechanisms",
        "conversation_id": "conv-1",
        "sources_to_use": ["pdf"],
        "retrieved_chunks": [],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
    }
    base.update(kwargs)
    return base


@pytest.mark.asyncio
async def test_retriever_queries_selected_sources():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "documents": [["chunk text"]],
        "metadatas": [[{"filename": "doc.pdf"}]],
        "distances": [[0.1]],
    }
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever.get_collection", return_value=mock_collection),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        result = await retriever_node(_base_state(sources_to_use=["pdf"]))

    assert len(result["retrieved_chunks"]) == 1
    assert result["retrieved_chunks"][0]["text"] == "chunk text"
    assert result["retrieved_chunks"][0]["source_type"] == "pdf"
    mock_collection.query.assert_called_once()


@pytest.mark.asyncio
async def test_retriever_deduplicates_chunks():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "documents": [["duplicate text", "duplicate text"]],
        "metadatas": [[{"filename": "a.pdf"}, {"filename": "b.pdf"}]],
        "distances": [[0.1, 0.2]],
    }
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever.get_collection", return_value=mock_collection),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        result = await retriever_node(_base_state(sources_to_use=["pdf"]))

    assert len(result["retrieved_chunks"]) == 1


@pytest.mark.asyncio
async def test_retriever_returns_empty_without_embedder():
    with patch("app.agent.nodes.retriever.get_embedder", return_value=None):
        result = await retriever_node(_base_state())

    assert result["retrieved_chunks"] == []
