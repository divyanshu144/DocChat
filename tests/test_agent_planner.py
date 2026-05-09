import pytest
from unittest.mock import AsyncMock, patch
from app.agent.state import AgentState
from app.agent.nodes.planner import planner_node


def _base_state() -> AgentState:
    return {
        "query": "What are attention mechanisms?",
        "conversation_id": "conv-1",
        "sources_to_use": [],
        "retrieved_chunks": [],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
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
