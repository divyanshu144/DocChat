import pytest
from unittest.mock import AsyncMock, patch
from app.agent.state import AgentState


@pytest.mark.asyncio
async def test_graph_runs_full_pipeline():
    planner_result = {"sources_to_use": ["pdf"], "query": "attention mechanisms"}
    retriever_result = {"retrieved_chunks": [{"text": "Attention is key.", "metadata": {}, "source_type": "pdf", "distance": 0.1}]}
    synthesizer_result = {"answer": "Attention allows focus on relevant parts."}
    critic_result = {"needs_replan": False, "iteration": 1, "critic_feedback": ""}

    with (
        patch("app.agent.nodes.planner.chat_complete", new=AsyncMock(
            return_value='{"sources_to_use": ["pdf"], "rewritten_query": "attention mechanisms"}')),
        patch("app.agent.nodes.synthesizer.chat_complete", new=AsyncMock(
            return_value="Attention allows focus on relevant parts.")),
        patch("app.agent.nodes.critic.chat_complete", new=AsyncMock(
            return_value='{"quality": "good", "feedback": ""}')),
        patch("app.agent.nodes.retriever.get_embedder") as mock_emb,
        patch("app.agent.nodes.retriever.get_collection") as mock_col,
    ):
        import numpy as np
        mock_emb.return_value.embed_query.return_value = np.array([0.1] * 384)
        mock_col.return_value.query.return_value = {
            "documents": [["Attention is key."]],
            "metadatas": [[{}]],
            "distances": [[0.1]],
        }

        from app.agent.graph import agent_graph
        initial_state: AgentState = {
            "query": "What is attention?",
            "conversation_id": "conv-1",
            "sources_to_use": ["pdf", "youtube", "web"],
            "retrieved_chunks": [],
            "answer": "",
            "critic_feedback": "",
            "needs_replan": False,
            "iteration": 0,
        }
        final_state = await agent_graph.ainvoke(initial_state)

    assert final_state["answer"] == "Attention allows focus on relevant parts."
    assert final_state["needs_replan"] is False
