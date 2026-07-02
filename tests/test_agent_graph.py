import pytest
from unittest.mock import AsyncMock, patch
from app.agent.state import AgentState


@pytest.mark.asyncio
async def test_graph_runs_full_pipeline():
    with (
        patch("app.agent.nodes.planner.chat_complete", new=AsyncMock(
            return_value='{"sources_to_use": ["pdf"], "rewritten_query": "attention mechanisms"}')),
        patch("app.agent.nodes.synthesizer.chat_complete", new=AsyncMock(
            return_value="Attention allows focus on relevant parts.")),
        patch("app.agent.nodes.grounding.chat_complete", new=AsyncMock(
            return_value="Attention allows focus on relevant parts.")),
        patch("app.agent.nodes.critic.chat_complete", new=AsyncMock(
            return_value='{"quality": "good", "feedback": ""}')),
        patch("app.agent.nodes.retriever.get_embedder") as mock_emb,
        patch("app.agent.nodes.retriever._search", new=AsyncMock(return_value=[
            {"payload": {"text": "Attention is key."}, "score": 0.9}
        ])),
    ):
        import numpy as np
        mock_emb.return_value.embed_query.return_value = np.array([0.1] * 384)

        from app.agent.graph import agent_graph
        initial_state: AgentState = {
            "query": "What is attention?",
            "conversation_id": "conv-1",
            "conversation_history": [],
            "sources_to_use": ["pdf", "youtube", "web"],
            "source_ids": [],
            "retrieved_chunks": [],
            "answer": "",
            "critic_feedback": "",
            "needs_replan": False,
            "iteration": 0,
            "grounding_passed": False,
        }
        final_state = await agent_graph.ainvoke(initial_state)

    assert final_state["answer"] == "Attention allows focus on relevant parts."
    assert final_state["needs_replan"] is False
    assert final_state["grounding_passed"] is True
