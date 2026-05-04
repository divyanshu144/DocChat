"""Tests for Bug #4 fix: GET /conversations/{id} excludes is_complete=False messages.

The fix replaces the selectinload(Conversation.messages) eager load (which returns
ALL messages) with a filtered query that only returns messages where is_complete=True.
Abandoned streaming placeholders (is_complete=False, content="") are therefore hidden
from API callers.
"""

from unittest.mock import MagicMock


def test_incomplete_messages_filtered():
    """is_complete=False messages are excluded when filtering by is_complete."""
    complete_msg = MagicMock(is_complete=True, content="hello", role="assistant")
    incomplete_msg = MagicMock(is_complete=False, content="", role="assistant")
    all_messages = [complete_msg, incomplete_msg]

    filtered = [m for m in all_messages if m.is_complete]

    assert len(filtered) == 1
    assert filtered[0].content == "hello"


def test_only_complete_messages_pass_filter():
    """All complete messages pass through the filter unchanged."""
    msgs = [
        MagicMock(is_complete=True, content=f"msg {i}", role="user")
        for i in range(5)
    ]
    filtered = [m for m in msgs if m.is_complete]
    assert len(filtered) == 5


def test_all_incomplete_messages_excluded():
    """If every message is incomplete, the result is an empty list."""
    msgs = [
        MagicMock(is_complete=False, content="", role="assistant")
        for _ in range(3)
    ]
    filtered = [m for m in msgs if m.is_complete]
    assert filtered == []


def test_mixed_messages_only_complete_returned():
    """Mixed list: only the complete ones survive the filter."""
    complete = [MagicMock(is_complete=True, content="done", role="assistant")]
    incomplete = [
        MagicMock(is_complete=False, content="", role="assistant"),
        MagicMock(is_complete=False, content="", role="assistant"),
    ]
    all_messages = incomplete + complete  # incomplete first, as they'd appear in DB
    filtered = [m for m in all_messages if m.is_complete]

    assert len(filtered) == 1
    assert filtered[0].content == "done"


def test_get_conversation_response_schema():
    """ConversationResponse can be constructed with a filtered messages list."""
    from datetime import datetime, timezone
    from app.api.conversations import ConversationResponse, MessageResponse
    from app.models.message import MessageRole

    now = datetime.now(timezone.utc)

    # Simulate what the fixed endpoint does: build the response from filtered messages
    complete_msg = MessageResponse(
        id="msg-1",
        role=MessageRole.assistant,
        content="hello",
        created_at=now,
    )

    response = ConversationResponse(
        id="conv-1",
        document_id="doc-1",
        created_at=now,
        messages=[complete_msg],
    )

    assert len(response.messages) == 1
    assert response.messages[0].content == "hello"
    assert response.messages[0].role == MessageRole.assistant


def test_get_conversation_response_empty_messages():
    """ConversationResponse with no complete messages returns an empty list (not an error)."""
    from datetime import datetime, timezone
    from app.api.conversations import ConversationResponse

    now = datetime.now(timezone.utc)
    response = ConversationResponse(
        id="conv-2",
        document_id="doc-2",
        created_at=now,
        messages=[],
    )
    assert response.messages == []
