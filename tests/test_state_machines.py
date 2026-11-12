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


# --- the local (BackgroundTasks) ingest path: _set_job -----------------------------------------------------------

@pytest.fixture
async def local_jobs(monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.models.conversation
    import app.models.refresh_token
    import app.models.user  # noqa: F401  (mapper registry)
    from app.api import ingest
    from app.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(ingest, "AsyncSessionLocal", factory)
    yield factory
    await engine.dispose()


async def _row(factory, job_id="L1"):
    from app.models.ingest_job import IngestJob

    async with factory() as session:
        return await session.get(IngestJob, job_id)


@pytest.mark.asyncio
async def test_local_set_job_walks_the_legal_path_and_creates_the_row_on_first_write(local_jobs):
    from app.api.ingest import _set_job
    from app.models.ingest_job import IngestJobStatusValue as S

    await _set_job("L1", source_type="web", status="running", phase="fetching", message="Fetching")
    assert (await _row(local_jobs)).status == S.running
    await _set_job("L1", status="done", phase="done", message="Ingested", source_id="s1")
    row = await _row(local_jobs)
    assert (row.status, row.source_id) == (S.done, "s1")


@pytest.mark.asyncio
async def test_local_set_job_never_reopens_a_finished_job(local_jobs):
    from app.api.ingest import _set_job
    from app.models.ingest_job import IngestJobStatusValue as S

    await _set_job("L1", source_type="web", status="done", phase="done", message="Ingested", source_id="s1")
    # A straggling progress callback, or the error handler of a duplicate run, arrives afterwards.
    await _set_job("L1", status="running", phase="embedding", message="late progress")
    await _set_job("L1", status="error", phase="error", message="Ingest failed", error="boom")

    row = await _row(local_jobs)
    assert (row.status, row.phase, row.message, row.source_id, row.error) == (S.done, "done", "Ingested", "s1", None)


@pytest.mark.asyncio
async def test_local_set_job_still_lets_an_errored_job_be_retried(local_jobs):
    from app.api.ingest import _set_job
    from app.models.ingest_job import IngestJobStatusValue as S

    await _set_job("L1", source_type="web", status="error", phase="error", message="Ingest failed", error="boom")
    await _set_job("L1", status="running", phase="fetching", message="Fetching")
    assert (await _row(local_jobs)).status == S.running
