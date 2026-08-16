"""Critic rejection sink — the only capture point for rejected drafts.

On replan the graph re-runs the synthesizer and overwrites `state["answer"]`, so a
draft the critic rejected exists nowhere else. These tests pin the two properties
that make the sink safe to leave enabled in production: it writes what we expect,
and it cannot take a chat request down with it.
"""

import json

import pytest
from unittest.mock import AsyncMock, patch

from app.agent.state import AgentState
from app.core.config import settings

_POOR = '{"quality": "poor", "feedback": "Missing the ChromaDB comparison."}'
_GOOD = '{"quality": "good", "feedback": ""}'


def _make_state(**kwargs) -> AgentState:
    base: AgentState = {
        "query": "What vector store does DocChat use?",
        "conversation_id": "conv-1",
        "conversation_history": [],
        "sources_to_use": ["pdf"],
        "source_ids": [],
        "retrieved_chunks": [
            {"text": "DocChat stores vectors in Qdrant.", "metadata": {}, "source_type": "pdf", "score": 0.9},
            {"text": "Qdrant uses HNSW indexing.", "metadata": {}, "source_type": "pdf", "score": 0.8},
        ],
        "answer": "DocChat uses Qdrant.",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
        "grounding_passed": False,
    }
    base.update(kwargs)
    return base


async def _run_critic(llm_response: str) -> dict:
    from app.agent.nodes.critic import critic_node

    with patch("app.agent.nodes.critic.chat_complete", new=AsyncMock(return_value=llm_response)):
        return await critic_node(_make_state())


@pytest.mark.asyncio
async def test_sink_disabled_by_default_writes_nothing(monkeypatch, tmp_path):
    """Blank path is a no-op — opting in must be deliberate, never accidental."""
    monkeypatch.setattr(settings, "critic_rejection_log", "")
    sink = tmp_path / "rejections.jsonl"

    result = await _run_critic(_POOR)

    assert result["needs_replan"] is True
    assert not sink.exists()


@pytest.mark.asyncio
async def test_rejected_answer_is_appended_as_one_jsonl_line(monkeypatch, tmp_path):
    sink = tmp_path / "nested" / "rejections.jsonl"   # parent must be created for us
    monkeypatch.setattr(settings, "critic_rejection_log", str(sink))

    await _run_critic(_POOR)

    lines = sink.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert set(record) == {"timestamp", "query", "answer", "context", "verdict", "reason"}
    assert record["query"] == "What vector store does DocChat use?"
    assert record["answer"] == "DocChat uses Qdrant."
    assert record["verdict"] == "poor"
    assert record["reason"] == "Missing the ChromaDB comparison."
    # Context is the retrieved chunks the draft was supposed to be grounded in —
    # without it a mined rejection cannot be relabelled by anything but the critic.
    assert "DocChat stores vectors in Qdrant." in record["context"]
    assert "Qdrant uses HNSW indexing." in record["context"]


@pytest.mark.asyncio
async def test_approved_answer_is_not_recorded(monkeypatch, tmp_path):
    sink = tmp_path / "rejections.jsonl"
    monkeypatch.setattr(settings, "critic_rejection_log", str(sink))

    result = await _run_critic(_GOOD)

    assert result["needs_replan"] is False
    assert not sink.exists()


@pytest.mark.asyncio
async def test_repeated_rejections_append_rather_than_truncate(monkeypatch, tmp_path):
    sink = tmp_path / "rejections.jsonl"
    monkeypatch.setattr(settings, "critic_rejection_log", str(sink))

    await _run_critic(_POOR)
    await _run_critic(_POOR)

    assert len(sink.read_text(encoding="utf-8").splitlines()) == 2


@pytest.mark.asyncio
async def test_unwritable_sink_never_breaks_the_node(monkeypatch, tmp_path):
    """A broken sink costs us training data. It must never cost a user their answer."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("i am a file", encoding="utf-8")
    monkeypatch.setattr(settings, "critic_rejection_log", str(blocker / "rejections.jsonl"))

    result = await _run_critic(_POOR)

    assert result["needs_replan"] is True
    assert result["critic_feedback"] == "Missing the ChromaDB comparison."
