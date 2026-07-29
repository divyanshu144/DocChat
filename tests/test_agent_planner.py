import pytest
from unittest.mock import AsyncMock, patch
from app.agent.state import AgentState
from app.agent.nodes.planner import planner_node


def _base_state() -> AgentState:
    return {
        "query": "What are attention mechanisms?",
        "conversation_id": "conv-1",
        "conversation_history": [],
        "sources_to_use": [],
        "source_ids": [],
        "retrieved_chunks": [],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
        "grounding_passed": False,
    }


@pytest.mark.asyncio
async def test_planner_selects_sources_from_llm_response():
    with patch("app.agent.nodes.planner.chat_complete",
               new=AsyncMock(return_value='{"sources_to_use": ["pdf", "web"], "rewritten_query": "attention mechanisms"}')):
        result = await planner_node(_base_state())

    assert result["sources_to_use"] == ["pdf", "web"]
    assert result["query"] == "attention mechanisms"


@pytest.mark.asyncio
async def test_planner_falls_back_on_invalid_json():
    with patch("app.agent.nodes.planner.chat_complete",
               new=AsyncMock(return_value="not valid json")):
        result = await planner_node(_base_state())

    assert set(result["sources_to_use"]) == {"pdf", "youtube", "web"}


@pytest.mark.asyncio
async def test_planner_filters_unknown_sources():
    with patch("app.agent.nodes.planner.chat_complete",
               new=AsyncMock(return_value='{"sources_to_use": ["pdf", "database", "web"], "rewritten_query": "test"}')):
        result = await planner_node(_base_state())

    assert "database" not in result["sources_to_use"]
    assert "pdf" in result["sources_to_use"]
    assert "web" in result["sources_to_use"]


@pytest.mark.asyncio
async def test_planner_uses_history_to_resolve_pronoun_reference():
    state = _base_state()
    state["query"] = "what was its revenue?"
    state["conversation_history"] = [
        {"role": "user", "content": "Tell me about the Q3 report"},
        {"role": "assistant", "content": "The Q3 report summarizes quarterly performance."},
    ]

    async def fake_chat_complete(messages, max_tokens=200):
        prompt = messages[0]["content"]
        assert "user: Tell me about the Q3 report" in prompt
        assert "Query: what was its revenue?" in prompt
        return '{"sources_to_use": ["pdf"], "rewritten_query": "What was the Q3 report revenue?"}'

    with patch("app.agent.nodes.planner.chat_complete", new=fake_chat_complete):
        result = await planner_node(state)

    assert result["query"] == "What was the Q3 report revenue?"
