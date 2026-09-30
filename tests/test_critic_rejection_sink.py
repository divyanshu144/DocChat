"""Critic rejection sink — the only capture point for rejected drafts.

On replan the graph re-runs the synthesizer and overwrites `state["answer"]`, so a
draft the critic rejected exists nowhere else. What gets written is a *pair*: the
rejected answer and the replacement that superseded it. Half a pair is not a training
example — supervised fine-tuning wants the preferred output, preference training wants
both sides, and neither can use a lone rejection.

These tests pin the three properties that make the sink safe to leave enabled in
production: it writes complete pairs, it never writes incomplete ones, and it cannot
take a chat request down with it.
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
        "pending_rejection": None,
    }
    base.update(kwargs)
    return base


async def _critic(state: AgentState, llm_response: str = _POOR) -> dict:
    from app.agent.nodes.critic import critic_node

    with patch("app.agent.nodes.critic.chat_complete", new=AsyncMock(return_value=llm_response)):
        return await critic_node(state)


async def _full_turn(sink_state: AgentState, replacement: str) -> dict:
    """First pass rejects, synthesizer replaces the answer, second pass closes the pair."""
    rejected = await _critic(sink_state)

    after_replan = _make_state(
        **{**{k: v for k, v in sink_state.items() if k != "answer"},
           "answer": replacement,
           "iteration": rejected["iteration"],
           "pending_rejection": rejected["pending_rejection"]}
    )
    return await _critic(after_replan)


# ---------------------------------------------------------------------------
# Opt-in
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sink_disabled_by_default_writes_nothing(monkeypatch, tmp_path):
    """Blank path is a no-op — opting in must be deliberate, never accidental."""
    monkeypatch.setattr(settings, "critic_rejection_log", "")
    sink = tmp_path / "rejections.jsonl"

    await _full_turn(_make_state(), replacement="DocChat uses Qdrant with HNSW.")

    assert not sink.exists()


@pytest.mark.asyncio
async def test_approved_answer_records_nothing(monkeypatch, tmp_path):
    sink = tmp_path / "rejections.jsonl"
    monkeypatch.setattr(settings, "critic_rejection_log", str(sink))

    result = await _critic(_make_state(), _GOOD)

    assert result["needs_replan"] is False
    assert result["pending_rejection"] is None
    assert not sink.exists()


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rejection_is_not_written_until_its_replacement_exists(monkeypatch, tmp_path):
    """The whole point of the redesign: a lone rejection is half a training example."""
    sink = tmp_path / "rejections.jsonl"
    monkeypatch.setattr(settings, "critic_rejection_log", str(sink))

    result = await _critic(_make_state())

    assert result["needs_replan"] is True
    assert result["pending_rejection"] is not None
    assert not sink.exists()


@pytest.mark.asyncio
async def test_completed_turn_writes_one_paired_record(monkeypatch, tmp_path):
    sink = tmp_path / "nested" / "rejections.jsonl"   # parent must be created for us
    monkeypatch.setattr(settings, "critic_rejection_log", str(sink))

    await _full_turn(_make_state(), replacement="DocChat uses Qdrant, chosen over ChromaDB for HNSW.")

    lines = sink.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert set(record) == {
        "rejection_id", "conversation_id", "rejected_at", "query", "context",
        "rejected_answer", "rejected_reason", "accepted_answer", "accepted_verdict",
        "accepted_at",
    }
    assert record["rejected_answer"] == "DocChat uses Qdrant."
    assert record["accepted_answer"] == "DocChat uses Qdrant, chosen over ChromaDB for HNSW."
    assert record["rejected_reason"] == "Missing the ChromaDB comparison."
    # Correlation back to the turn this came from — without it a mined record is orphaned.
    assert record["conversation_id"] == "conv-1"
    assert record["rejection_id"]
    # Context is the retrieved chunks the draft was grounded in; without it a mined
    # record cannot be relabelled by anything but the critic that rejected it.
    assert "DocChat stores vectors in Qdrant." in record["context"]


@pytest.mark.asyncio
async def test_accepted_verdict_records_that_no_second_opinion_was_taken(monkeypatch, tmp_path):
    """The replacement is accepted by exhausting the retry budget, not by approval.
    Mislabelling it as approved would overstate the quality of the preferred side."""
    sink = tmp_path / "rejections.jsonl"
    monkeypatch.setattr(settings, "critic_rejection_log", str(sink))

    await _full_turn(_make_state(), replacement="A better answer.")

    record = json.loads(sink.read_text(encoding="utf-8").splitlines()[0])
    assert record["accepted_verdict"] == "accepted_by_iteration_cap"


@pytest.mark.asyncio
async def test_repeated_turns_append_rather_than_overwrite(monkeypatch, tmp_path):
    sink = tmp_path / "rejections.jsonl"
    monkeypatch.setattr(settings, "critic_rejection_log", str(sink))

    await _full_turn(_make_state(), replacement="First replacement.")
    await _full_turn(_make_state(), replacement="Second replacement.")

    lines = sink.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert {json.loads(line)["rejection_id"] for line in lines}.__len__() == 2


@pytest.mark.asyncio
async def test_second_pass_without_a_pending_rejection_writes_nothing(monkeypatch, tmp_path):
    """A turn that was never rejected has no pair to write, even at the iteration cap."""
    sink = tmp_path / "rejections.jsonl"
    monkeypatch.setattr(settings, "critic_rejection_log", str(sink))

    result = await _critic(_make_state(iteration=1, pending_rejection=None))

    assert result["needs_replan"] is False
    assert not sink.exists()


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unwritable_sink_never_breaks_the_node(monkeypatch, tmp_path):
    """A broken sink costs us training data. It must never cost a user their answer."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("i am a file", encoding="utf-8")
    monkeypatch.setattr(settings, "critic_rejection_log", str(blocker / "rejections.jsonl"))

    result = await _full_turn(_make_state(), replacement="A replacement.")

    assert result["needs_replan"] is False
    assert result["pending_rejection"] is None
