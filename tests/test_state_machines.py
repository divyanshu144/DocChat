"""The small state machines that used to be implicit: replan budget, worker state, expiring quirk flags,
sparse-model retry, span outcomes."""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.agent.graph import _route_critic
from app.agent.state import MAX_PASSES, budget_spent


def test_replan_budget_is_one_predicate_shared_by_graph_and_critic():
    assert MAX_PASSES == 2
    assert [budget_spent(i) for i in range(4)] == [False, False, True, True]
    # The graph only loops back while the budget is unspent.
    assert _route_critic({"needs_replan": True, "iteration": 1}) == "planner"
    assert _route_critic({"needs_replan": True, "iteration": MAX_PASSES}) != "planner"
    assert _route_critic({"needs_replan": False, "iteration": 0}) != "planner"


@pytest.mark.asyncio
async def test_critic_stops_asking_for_a_replan_exactly_when_the_graph_would_stop_routing():
    from app.agent.nodes.critic import critic_node

    out = await critic_node({"original_query": "q", "query": "q", "answer": "a", "iteration": MAX_PASSES - 1,
                             "retrieved_chunks": [], "pending_rejection": None})
    assert out["needs_replan"] is False and budget_spent(out["iteration"])


def test_worker_state_is_a_single_value_with_a_fixed_precedence():
    from app.worker.loop import MAX_POLL_ERRORS, Worker

    w = Worker(MagicMock(), MagicMock())
    assert w.state == "cold" and not w.ready
    w.warm = True
    assert w.state == "ready" and w.ready
    w.poll_errors = MAX_POLL_ERRORS
    assert w.state == "degraded" and not w.ready
    w.poll_errors = 0
    w.stop()
    assert w.state == "stopping" and not w.ready
    w.warm = False  # stopping outranks cold
    assert w.state == "stopping"


def test_temperature_quirk_flag_expires_instead_of_sticking_forever():
    from app.services.llm import _ExpiringSet

    flags = _ExpiringSet(ttl_s=10)
    with patch("app.services.llm.time.monotonic", return_value=100.0):
        flags.add("m")
        assert "m" in flags and len(flags) == 1
    with patch("app.services.llm.time.monotonic", return_value=109.0):
        assert "m" in flags
    with patch("app.services.llm.time.monotonic", return_value=111.0):
        assert "m" not in flags and not flags  # probed again next call


def test_sparse_model_is_retried_after_the_cooldown_not_only_at_restart():
    from app.services import embedder as emb

    with patch("app.services.embedder.TextEmbedding", return_value=MagicMock()):
        e = emb._Embedder("dense")
    ok = MagicMock()
    clock = {"t": 1000.0}
    with patch("app.services.embedder.time.monotonic", side_effect=lambda: clock["t"]), \
         patch("app.services.embedder.SparseTextEmbedding", side_effect=[RuntimeError("boom"), ok]) as factory:
        assert e.has_sparse is False
        assert e.has_sparse is False                       # inside the cooldown: not retried
        assert factory.call_count == 1
        clock["t"] += emb.SPARSE_RETRY_S + 1
        assert e.has_sparse is True                        # recovered without a restart
        assert factory.call_count == 2


def test_outcome_for_separates_cancellation_from_failure():
    from app.core.telemetry import OUTCOMES, outcome_for

    assert outcome_for(asyncio.CancelledError()) == "cancelled"
    assert outcome_for(GeneratorExit()) == "cancelled"
    assert outcome_for(RuntimeError("x")) == "error"
    assert {outcome_for(asyncio.CancelledError()), outcome_for(ValueError())} <= set(OUTCOMES)


def test_a_cancelled_span_has_no_error_type():
    from app.core.telemetry import span

    with pytest.raises(asyncio.CancelledError):
        with span("t") as record:
            raise asyncio.CancelledError()
    assert record["outcome"] == "cancelled" and "error_type" not in record
