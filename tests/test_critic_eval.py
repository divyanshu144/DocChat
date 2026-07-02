import pytest
from eval.cases import CASES
from app.agent.nodes.critic import critic_node
from app.agent.state import AgentState

pytestmark = [pytest.mark.eval, pytest.mark.asyncio]


@pytest.mark.parametrize("case", CASES, ids=[c.label for c in CASES])
async def test_critic_eval(case):
    state: AgentState = {
        "query": case.query,
        "answer": case.answer,
        "iteration": 0,           # must be 0 — critic short-circuits at >= 2 without LLM call
        "conversation_id": "",
        "conversation_history": [],
        "sources_to_use": ["pdf"],
        "source_ids": [],
        "retrieved_chunks": [],
        "critic_feedback": "",
        "needs_replan": False,
        "grounding_passed": False,
    }

    result = await critic_node(state)

    assert result["needs_replan"] == (case.expected == "poor"), (
        f"\n[{case.label}] "
        f"expected={'poor' if case.expected == 'poor' else 'good'} "
        f"got needs_replan={result['needs_replan']}\n"
        f"Reason: {case.reason}\n"
        f"Critic feedback: {result.get('critic_feedback', '')}"
    )
