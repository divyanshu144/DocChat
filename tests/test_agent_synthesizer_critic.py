import pytest
from unittest.mock import AsyncMock, patch
from app.agent.state import AgentState


def _make_state(**kwargs) -> AgentState:
    base: AgentState = {
        "query": "What is attention?",
        "conversation_id": "conv-1",
        "sources_to_use": ["pdf"],
        "retrieved_chunks": [
            {
                "text": "Attention allows models to focus on relevant parts.",
                "metadata": {"filename": "paper.pdf", "page_number": 3},
                "source_type": "pdf",
                "distance": 0.1,
            }
        ],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
    }
    base.update(kwargs)
    return base


@pytest.mark.asyncio
async def test_synthesizer_produces_answer():
    from app.agent.nodes.synthesizer import synthesizer_node
    with patch("app.agent.nodes.synthesizer.chat_complete",
               new=AsyncMock(return_value="Attention focuses on relevant parts.")):
        result = await synthesizer_node(_make_state())
    assert result["answer"] == "Attention focuses on relevant parts."


@pytest.mark.asyncio
async def test_synthesizer_formats_pdf_citation():
    from app.agent.nodes.synthesizer import synthesizer_node, _format_chunks
    chunks = [{"text": "some text", "metadata": {"filename": "doc.pdf", "page_number": 5}, "source_type": "pdf", "distance": 0.1}]
    formatted = _format_chunks(chunks)
    assert "PDF" in formatted
    assert "doc.pdf" in formatted
    assert "p.5" in formatted


@pytest.mark.asyncio
async def test_critic_approves_good_answer():
    from app.agent.nodes.critic import critic_node
    with patch("app.agent.nodes.critic.chat_complete",
               new=AsyncMock(return_value='{"quality": "good", "feedback": ""}')):
        result = await critic_node(_make_state(answer="Attention focuses on relevant parts."))
    assert result["needs_replan"] is False
    assert result["iteration"] == 1


@pytest.mark.asyncio
async def test_critic_requests_replan_on_poor_answer():
    from app.agent.nodes.critic import critic_node
    with patch("app.agent.nodes.critic.chat_complete",
               new=AsyncMock(return_value='{"quality": "poor", "feedback": "Missing mathematical definition."}')):
        result = await critic_node(_make_state(answer="I don't know.", iteration=0))
    assert result["needs_replan"] is True
    assert "Missing" in result["critic_feedback"]


@pytest.mark.asyncio
async def test_critic_stops_at_max_iterations():
    from app.agent.nodes.critic import critic_node
    with patch("app.agent.nodes.critic.chat_complete",
               new=AsyncMock(return_value='{"quality": "poor", "feedback": "still bad"}')):
        result = await critic_node(_make_state(answer="bad answer", iteration=1))
    assert result["needs_replan"] is False
    assert result["iteration"] == 2
