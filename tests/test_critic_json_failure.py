from unittest.mock import AsyncMock, patch
import pytest


@pytest.mark.asyncio
async def test_critic_warns_when_json_is_invalid(caplog):
    from app.agent.nodes.critic import critic_node

    with patch("app.agent.nodes.critic.chat_complete", AsyncMock(return_value="not JSON")):
        result = await critic_node({"query": "test", "answer": "test", "iteration": 0})
    assert not result["needs_replan"]
    assert "critic_json_parse_failed" in caplog.text
