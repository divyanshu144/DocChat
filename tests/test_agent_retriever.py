import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch
from app.agent.state import AgentState
from app.agent.nodes.retriever import retriever_node


@pytest.mark.asyncio
async def test_search_reuses_client_and_reads_current_settings(monkeypatch):
    import httpx
    from app.agent.nodes import retriever

    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"result": [_search_hit("chunk")]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch.object(retriever.httpx, "AsyncClient", return_value=client) as factory:
        try:
            monkeypatch.setattr(retriever.settings, "qdrant_host", "first-host")
            monkeypatch.setattr(retriever.settings, "qdrant_port", 6333)
            assert await retriever._search("source_chunks", [0.1], 8) == [_search_hit("chunk")]
            monkeypatch.setattr(retriever.settings, "qdrant_host", "second-host")
            monkeypatch.setattr(retriever.settings, "qdrant_port", 7333)
            await retriever._search("source_chunks", [0.1], 8)
            factory.assert_called_once_with(timeout=30.0)
            assert requests[0].url.host == "first-host"
            assert requests[1].url.host == "second-host"
            assert requests[1].url.port == 7333
            assert not client.is_closed
        finally:
            await retriever.close_retriever_client()
    assert client.is_closed
    await retriever.close_retriever_client()  # shutdown is idempotent


def test_retriever_clients_are_not_shared_between_event_loops():
    import asyncio
    from app.agent.nodes import retriever

    async def use_client():
        client = retriever._get_http_client()
        assert retriever._get_http_client() is client
        return client

    first_loop = asyncio.new_event_loop()
    second_loop = asyncio.new_event_loop()
    try:
        first = first_loop.run_until_complete(use_client())
        second = second_loop.run_until_complete(use_client())
        assert first is not second
        assert not first.is_closed and not second.is_closed
    finally:
        first_loop.run_until_complete(retriever.close_retriever_client())
        second_loop.run_until_complete(retriever.close_retriever_client())
        first_loop.close()
        second_loop.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("server_type", ["api", "mcp"])
async def test_server_lifespan_closes_retriever_client_on_failure(server_type):
    from app.agent.nodes import retriever
    from app.main import lifespan
    from app.mcp_server import _lifespan

    context = lifespan if server_type == "api" else _lifespan
    with (
        patch("app.main._refuse_default_secret_in_production"),
        patch("app.main.create_all_tables", new=AsyncMock()),
    ):
        with pytest.raises(RuntimeError, match="handler failed"):
            async with context(None):
                client = retriever._get_http_client()
                raise RuntimeError("handler failed")
    assert client.is_closed


def _search_hit(text: str, score: float = 0.8, **payload_extra):
    return {
        "score": score,
        "payload": {"text": text, "source_type": "pdf", "filename": "doc.pdf", **payload_extra},
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
        patch("app.agent.nodes.retriever._search", new=AsyncMock(return_value=[_search_hit("chunk text", score=0.75)])) as mock_search,
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        result = await retriever_node(_base_state(sources_to_use=["pdf"]))

    assert mock_search.call_args.args[0] == "source_chunks"
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
async def test_retriever_source_id_filter_ignores_known_source_type_filter():
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever._search", new=AsyncMock(return_value=[_search_hit("filtered chunk")])) as mock_search,
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        await retriever_node(_base_state(sources_to_use=["pdf"], source_ids=["src-future"]))

    dumped_filter = mock_search.call_args.args[3].model_dump(mode="json", exclude_none=True)
    fields = [condition["key"] for condition in dumped_filter["must"]]
    assert fields == ["source_id"]


@pytest.mark.asyncio
async def test_retriever_reranks_lexical_matches_above_weaker_vector_hits():
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever._search", new=AsyncMock(return_value=[
            _search_hit("generic unrelated chunk", score=0.9),
            _search_hit("attention mechanisms explain relevant context", score=0.82),
        ])),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        result = await retriever_node(_base_state())

    assert result["retrieved_chunks"][0]["text"] == "attention mechanisms explain relevant context"


@pytest.mark.asyncio
async def test_retriever_drops_chunks_below_retrieval_min_score():
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever._search", new=AsyncMock(return_value=[
            _search_hit("below threshold", score=0.1),
        ])),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
        patch("app.agent.nodes.retriever.settings.retrieval_min_score", 0.3),
    ):
        result = await retriever_node(_base_state())

    assert result["retrieved_chunks"] == []


@pytest.mark.asyncio
async def test_retriever_keeps_chunks_at_or_above_retrieval_min_score():
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever._search", new=AsyncMock(return_value=[
            _search_hit("exactly at threshold", score=0.3),
        ])),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
        patch("app.agent.nodes.retriever.settings.retrieval_min_score", 0.3),
    ):
        result = await retriever_node(_base_state())

    assert len(result["retrieved_chunks"]) == 1


@pytest.mark.asyncio
async def test_retriever_filters_a_mix_of_high_and_low_score_hits():
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever._search", new=AsyncMock(return_value=[
            _search_hit("good hit", score=0.8),
            _search_hit("noise hit", score=0.05),
        ])),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
        patch("app.agent.nodes.retriever.settings.retrieval_min_score", 0.3),
    ):
        result = await retriever_node(_base_state())

    assert [c["text"] for c in result["retrieved_chunks"]] == ["good hit"]


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
