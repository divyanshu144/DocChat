import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    from app.core.database import get_db

    async def mock_db():
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        session.flush = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)
        yield session

    app.dependency_overrides[get_db] = mock_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_chat_streams_sse_answer(client):
    final_state = {
        "query": "What is attention?",
        "conversation_id": "conv-123",
        "sources_to_use": ["pdf"],
        "retrieved_chunks": [],
        "answer": "Attention is a mechanism.",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 1,
    }

    with patch("app.api.chat.agent_graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=final_state)
        response = client.post(
            "/api/v1/chat",
            json={"query": "What is attention?"},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "Attention" in response.text
    assert "[DONE]" in response.text
