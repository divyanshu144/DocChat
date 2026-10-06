import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.api.chat import _TOKEN_SPLIT_RE, _run_agent_with_status, _sse


def _decode_sse_events(raw: str) -> list[tuple[str, str]]:
    """Minimal SSE decoder for tests: returns [(event, data), ...], joining
    consecutive data: lines within one event with "\\n" -- the same
    reconstruction frontend/src/api.ts's stream reader does. Used to prove
    an answer round-trips through _sse's encoding byte for byte. Matches
    _sse's own framing exactly: every data line is "data: " plus content,
    even when content is empty."""
    events = []
    event_type = "message"
    data_lines: list[str] = []
    for line in raw.split("\n"):
        if line.startswith("event: "):
            event_type = line[len("event: "):]
        elif line.startswith("data: "):
            data_lines.append(line[len("data: "):])
        elif line == "":
            if data_lines:
                events.append((event_type, "\n".join(data_lines)))
            event_type = "message"
            data_lines = []
    return events


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


def test_chat_history_query_uses_configured_chat_history_limit(client):
    """settings.chat_history_limit must actually drive the query, not a
    hardcoded number -- was dead config before this fix."""
    from app.core.config import settings

    with patch.object(settings, "chat_history_limit", 3), \
         patch("app.api.chat.agent_graph") as mock_graph:
        async def fake_astream(*_args, **_kwargs):
            yield {"synthesizer": {"answer": "ok"}}

        mock_graph.astream = fake_astream
        client.post("/api/v1/chat", json={"query": "hi"})

    from app.main import app
    session = app.state.test_db_session
    history_call = next(
        call for call in session.execute.call_args_list
        if "messages" in str(call.args[0]).lower()
    )
    compiled = str(history_call.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "LIMIT 3" in compiled


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


# ---------------------------------------------------------------------------
# _sse / _TOKEN_SPLIT_RE (Part 2 B): whitespace-preserving streaming
# ---------------------------------------------------------------------------


def test_sse_single_line_data_is_unchanged_shape():
    assert _sse("status", "Reading your question") == (
        "event: status\ndata: Reading your question\n\n"
    )


def test_sse_multiline_data_becomes_multiple_data_lines():
    raw = _sse("token", "hello\nworld")
    assert raw == "event: token\ndata: hello\ndata: world\n\n"


def test_sse_decoder_reconstructs_multiline_data_with_newline_join():
    raw = _sse("token", "hello\nworld")
    events = _decode_sse_events(raw)
    assert events == [("token", "hello\nworld")]


def test_token_split_preserves_a_single_newline_between_words():
    pieces = _TOKEN_SPLIT_RE.findall("hello\nworld")
    assert "".join(pieces) == "hello\nworld"
    assert any("\n" in p for p in pieces)


def test_token_split_preserves_a_paragraph_break():
    text = "First paragraph.\n\nSecond paragraph."
    pieces = _TOKEN_SPLIT_RE.findall(text)
    assert "".join(pieces) == text


def test_answer_with_newlines_round_trips_through_the_full_sse_stream(client):
    """The actual fix end to end: an answer with embedded newlines, sent
    through the real token-splitting and SSE-encoding path this endpoint
    uses, reconstructs byte for byte on the decoding side."""
    answer = "Line one.\n\nLine two has a list:\n- item a\n- item b\n\nLine three."
    with patch("app.api.chat.agent_graph") as mock_graph:
        async def fake_astream(*_args, **_kwargs):
            yield {"synthesizer": {"answer": answer}}

        mock_graph.astream = fake_astream
        response = client.post("/api/v1/chat", json={"query": "multi-line please"})

    assert response.status_code == 200
    events = _decode_sse_events(response.text)
    token_events = [data for event, data in events if event == "token"]
    reconstructed = "".join(token_events)
    assert reconstructed == answer


def test_chat_telemetry_records_sse_error_despite_http_200(client, monkeypatch):
    from app.core import telemetry
    records = []
    monkeypatch.setattr(telemetry, "emit", lambda row: records.append(dict(row)))

    async def broken_graph(*args, **kwargs):
        raise RuntimeError("failed before answer")
        yield  # async generator contract

    with patch("app.api.chat.agent_graph") as graph:
        graph.astream = broken_graph
        response = client.post("/api/v1/chat", json={"query": "hi"},
                               headers={"X-Request-Id": "chat-error"})
    assert response.status_code == 200
    assert "event: error" in response.text
    request = next(r for r in records if r["event"] == "request")
    assert request["outcome"] == "error"
    assert request["first_answer_s"] is None
    assert request["request_id"] == response.headers["x-request-id"] == "chat-error"


@pytest.mark.asyncio
async def test_sustained_api_client_consumes_real_chat_sse(client):
    import httpx
    from eval.serving_load import api_request
    from eval.workloads import WorkloadCase
    async def fake_astream(*args, **kwargs):
        yield {"synthesizer": {"answer": "First line.\nSecond line.\nSources: [Web — example.org]"}}
    with patch("app.api.chat.agent_graph") as graph:
        graph.astream = fake_astream
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app),
                                     base_url="http://test/api/v1/") as api_client:
            row = await api_request(api_client, WorkloadCase(
                id="qa", category="document_qa", query="question"), "integration-test")
    assert row["status"] == "ok"
    assert row["first_answer_s"] is not None
    assert row["ttft_s"] is None and row["output_tokens"] is None
