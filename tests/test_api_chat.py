import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.api.chat import _run_agent_with_status


@pytest.fixture
def client():
    from app.main import app
    from app.core.database import get_db
    from app.core.deps import get_current_user

    async def mock_db():
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        session.flush = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        app.state.test_db_session = session
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)
        yield session

    fake_user = MagicMock()
    fake_user.id = "user-test-id"
    fake_user.is_active = True

    async def mock_current_user():
        return fake_user

    app.dependency_overrides[get_db] = mock_db
    app.dependency_overrides[get_current_user] = mock_current_user
    yield TestClient(app)
    app.dependency_overrides.clear()
    if hasattr(app.state, "test_db_session"):
        del app.state.test_db_session


def test_chat_streams_sse_answer(client):
    with patch("app.api.chat.agent_graph") as mock_graph:
        async def fake_astream(*_args, **_kwargs):
            yield {"planner": {"sources_to_use": ["pdf"]}}
            yield {"retriever": {"retrieved_chunks": []}}
            yield {"synthesizer": {"answer": "Attention is a mechanism."}}
            yield {"grounding": {"answer": "Attention is a mechanism.", "grounding_passed": True}}
            yield {"critic": {"needs_replan": False, "iteration": 1}}

        mock_graph.astream = fake_astream
        response = client.post(
            "/api/v1/chat",
            json={"query": "What is attention?"},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: status" in response.text
    assert "Planning which sources to search" in response.text
    assert "event: token" in response.text
    assert "Attention" in response.text
    assert "[DONE]" in response.text


def test_chat_commits_new_conversation_before_streaming(client):
    with patch("app.api.chat.agent_graph") as mock_graph:
        async def fake_astream(*_args, **_kwargs):
            assert client.app.state.test_db_session.commit.await_count == 1
            yield {"synthesizer": {"answer": "Committed before streaming."}}

        mock_graph.astream = fake_astream
        response = client.post(
            "/api/v1/chat",
            json={"query": "Create a conversation"},
        )

    assert response.status_code == 200
    assert client.app.state.test_db_session.commit.await_count == 2


def test_chat_streams_rate_limit_error_message(client):
    with patch("app.api.chat.agent_graph") as mock_graph:
        async def fake_astream(*_args, **_kwargs):
            raise RuntimeError("429 Too Many Requests")
            yield

        mock_graph.astream = fake_astream
        response = client.post(
            "/api/v1/chat",
            json={"query": "What is attention?"},
        )

    assert response.status_code == 200
    assert "event: error" in response.text
    assert "rate-limiting" in response.text


@pytest.mark.asyncio
async def test_agent_status_runner_preserves_last_non_empty_answer():
    initial_state = {
        "query": "Explain prompt chaining",
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

    with patch("app.api.chat.agent_graph") as mock_graph:
        async def fake_astream(*_args, **_kwargs):
            yield {"synthesizer": {"answer": "Prompt chaining splits a task into steps."}}
            yield {"grounding": {"answer": "", "grounding_passed": False}}

        mock_graph.astream = fake_astream
        events = [event async for event in _run_agent_with_status(initial_state)]

    final = events[-1][1]
    assert final["answer"] == "Prompt chaining splits a task into steps."


def test_chat_never_streams_empty_saved_answer(client):
    with patch("app.api.chat.agent_graph") as mock_graph:
        async def fake_astream(*_args, **_kwargs):
            yield {"planner": {"sources_to_use": ["pdf"]}}
            yield {"synthesizer": {"answer": ""}}

        mock_graph.astream = fake_astream
        response = client.post(
            "/api/v1/chat",
            json={"query": "Explain prompt chaining"},
        )

    assert response.status_code == 200
    assert "couldn't" in response.text
    assert "usable" in response.text
    assert "event: token" in response.text
