import pytest
from unittest.mock import patch, AsyncMock
from app.agent.state import AgentState
from app.agent.nodes.grounding import grounding_node, _looks_like_grounding_failure


def _base_state(**kwargs) -> AgentState:
    base = {
        "query": "What is attention?",
        "conversation_id": "conv-1",
        "conversation_history": [],
        "sources_to_use": ["pdf"],
        "source_ids": [],
        "retrieved_chunks": [
            {
                "text": "Attention is a mechanism that allows the model to focus on relevant parts.",
                "metadata": {"filename": "paper.pdf", "page_number": 3},
                "source_type": "pdf",
                "score": 0.9,
            }
        ],
        "answer": "Attention is a mechanism. [PDF — paper.pdf p.3] The sky is green.",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
        "grounding_passed": False,
    }
    base.update(kwargs)
    return base


@pytest.mark.asyncio
async def test_grounding_passes_through_on_llm_failure():
    """If LLM call raises, original answer is preserved."""
    with patch(
        "app.agent.nodes.grounding.chat_complete",
        new_callable=AsyncMock,
        side_effect=Exception("LLM error"),
    ):
        result = await grounding_node(_base_state())

    assert result["answer"] == "Attention is a mechanism. [PDF — paper.pdf p.3] The sky is green."
    assert result["grounding_passed"] is False


@pytest.mark.asyncio
async def test_grounding_updates_answer_with_verified_text():
    """LLM returns cleaned answer — grounding_node stores it and sets grounding_passed=True."""
    cleaned = "Attention is a mechanism. [PDF — paper.pdf p.3]"
    with patch(
        "app.agent.nodes.grounding.chat_complete",
        new_callable=AsyncMock,
        return_value=cleaned,
    ) as mock_llm:
        result = await grounding_node(_base_state())

    messages = mock_llm.await_args.args[0]
    assert "Preserve helpful Markdown structure" in messages[0]["content"]
    assert messages[1]["content"].startswith("Answer to clean:")
    assert mock_llm.await_args.kwargs["max_tokens"] == 1400
    assert result["answer"] == cleaned
    assert result["grounding_passed"] is True


@pytest.mark.asyncio
async def test_grounding_skips_when_no_chunks():
    """No retrieved chunks → skip LLM call, pass through answer unchanged."""
    state = _base_state(retrieved_chunks=[], answer="Some answer.")
    with patch("app.agent.nodes.grounding.chat_complete", new_callable=AsyncMock) as mock_llm:
        result = await grounding_node(state)

    mock_llm.assert_not_called()
    assert result["answer"] == "Some answer."
    assert result["grounding_passed"] is False


@pytest.mark.asyncio
async def test_grounding_preserves_original_when_cleaner_returns_meta_failure():
    original = (
        "One design pattern is a reusable approach for coordinating agent behavior. "
        "It explains when to retrieve context, how to route work, and how to verify the "
        "result before presenting the final answer."
    )
    with patch(
        "app.agent.nodes.grounding.chat_complete",
        new_callable=AsyncMock,
        return_value="I don't have an answer to clean.",
    ):
        result = await grounding_node(_base_state(answer=original))

    assert result["answer"] == original
    assert result["grounding_passed"] is False


def test_grounding_failure_detection_distinguishes_short_valid_answers():
    assert _looks_like_grounding_failure("No.", "Is coding dead?") is False
    assert _looks_like_grounding_failure(
        "I don't have an answer to clean.",
        "A much longer original answer that should not be replaced by a meta failure.",
    ) is True
