from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
import pytest


@pytest.mark.asyncio
async def test_replan_graph_keeps_original_question():
    from app.agent.graph import agent_graph

    question = "Compare the benefits and risks of attention"
    embedder = MagicMock()
    embedder.embed_query.return_value = np.array([0.1] * 384)
    with (
        patch("app.agent.nodes.planner.chat_complete", AsyncMock(side_effect=[
            '{"sources_to_use":["pdf"],"rewritten_query":"attention benefits"}',
            '{"sources_to_use":["pdf"],"rewritten_query":"attention risks"}',
        ])),
        patch("app.agent.nodes.retriever.get_embedder", return_value=embedder),
        patch("app.agent.nodes.retriever._search", AsyncMock(return_value=[
            {"score": 0.9, "payload": {"text": "Benefits and risks", "source_type": "pdf"}}
        ])),
        patch("app.agent.nodes.synthesizer.chat_complete", AsyncMock(return_value="Draft")) as synth,
        patch("app.agent.nodes.grounding.chat_complete", AsyncMock(return_value="Draft")),
        patch("app.agent.nodes.critic.chat_complete", AsyncMock(return_value=
              '{"quality":"poor","feedback":"include risks"}')) as critic,
    ):
        result = await agent_graph.ainvoke({
            "query": question, "original_query": question, "conversation_history": [],
            "retrieved_chunks": [], "iteration": 0, "answer": "", "conversation_id": "test",
        })
    assert result["original_query"] == question
    assert result["query"] == "attention risks"
    assert synth.await_count == 2
    assert all(call.args[0][-1]["content"] == question for call in synth.await_args_list)
    assert f"Query: {question}" in critic.call_args.args[0][0]["content"]
    assert [call.args[0] for call in embedder.embed_query.call_args_list] == ["attention benefits", "attention risks"]



@pytest.mark.asyncio
async def test_mcp_sets_original_question_before_invoking_graph():
    from app.mcp_server import query_documents

    with patch("app.agent.graph.agent_graph.ainvoke", AsyncMock(return_value={"answer": "answer"})) as invoke:
        await query_documents("original question")
    assert invoke.call_args.args[0]["original_query"] == "original question"
