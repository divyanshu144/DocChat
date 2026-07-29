import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch
from app.agent.state import AgentState
from app.agent.nodes.retriever import retriever_node


def _search_hit(text: str, score: float = 0.8, **payload_extra):
    return {
        "score": score,
        "payload": {"text": text, "filename": "doc.pdf", **payload_extra},
    }


def _base_state(**kwargs) -> AgentState:
    base: AgentState = {
        "query": "attention mechanisms",
        "conversation_id": "conv-1",
        "conversation_history": [],
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
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever._search", new=AsyncMock(return_value=[_search_hit("chunk text", score=0.75)])),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        result = await retriever_node(_base_state(sources_to_use=["pdf"]))

    assert len(result["retrieved_chunks"]) == 1
    assert result["retrieved_chunks"][0]["text"] == "chunk text"
    assert result["retrieved_chunks"][0]["source_type"] == "pdf"
    assert result["retrieved_chunks"][0]["score"] == 0.75


@pytest.mark.asyncio
async def test_retriever_deduplicates_chunks():
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever._search", new=AsyncMock(return_value=[
            _search_hit("duplicate text", score=0.8),
            _search_hit("duplicate text", score=0.7),
        ])),
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
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever._search", new=AsyncMock(return_value=[_search_hit("filtered chunk")])) as mock_search,
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        await retriever_node(_base_state(sources_to_use=["pdf"], source_ids=["src-123"]))

    assert mock_search.call_args.args[3] is not None


@pytest.mark.asyncio
async def test_retriever_does_not_write_to_stdout(capsys):
    """No print() calls should survive in retriever_node — they corrupt the MCP stdio channel."""
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever._search", new=AsyncMock(return_value=[])),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        await retriever_node(_base_state())

    captured = capsys.readouterr()
    assert captured.out == "", f"unexpected stdout from retriever_node: {captured.out!r}"
