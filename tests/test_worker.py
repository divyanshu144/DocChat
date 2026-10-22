"""Worker loop: concurrency bound, poison messages, graceful shutdown, probes and metrics. No AWS."""
import asyncio
import threading
import urllib.error
import urllib.request

import pytest

from app.core.metrics import metrics
from app.services.queueing import IngestMessage, ReceivedMessage
from app.worker import loop as worker_loop
from app.worker.loop import Worker
from app.worker.server import make_server, serve_in_thread


def msg(i):
    return IngestMessage(job_id=f"j{i}", source_type="web", url=f"https://example.com/{i}")


class ScriptedQueue:
    """Hands out `batches` once, then empty polls (after a short sleep, like a long poll)."""

    def __init__(self, batches):
        self.batches, self.visibility, self.deleted = list(batches), [], []
        self.lock = threading.Lock()

    def receive(self, n, wait):
        with self.lock:
            if self.batches:
                batch = self.batches.pop(0)
                if len(batch) > n:  # like SQS: at most n now, the rest stays queued
                    self.batches.insert(0, batch[n:])
                return batch[:n]
        import time
        time.sleep(0.02)
        return []

    def change_visibility(self, receipt, seconds):
        self.visibility.append((receipt, seconds))

    def delete(self, receipt):
        self.deleted.append(receipt)


async def run_until(worker, condition, timeout=5):
    task = asyncio.create_task(worker.run())
    for _ in range(int(timeout / 0.01)):
        if condition():
            break
        await asyncio.sleep(0.01)
    worker.stop()
    await asyncio.wait_for(task, 10)


async def test_processes_messages_with_bounded_concurrency(monkeypatch):
    running, peak, done = 0, 0, []

    async def fake_process(received, queue, blobs):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        done.append(received.receipt)
        return "done"

    monkeypatch.setattr(worker_loop, "process_message", fake_process)
    q = ScriptedQueue([[ReceivedMessage(f"r{i}", 1, msg(i)) for i in range(6)]])
    worker = Worker(q, object(), concurrency=2, wait_seconds=0)
    worker.warm = True
    await run_until(worker, lambda: len(done) == 6)
    assert sorted(done) == [f"r{i}" for i in range(6)] and peak == 2


async def test_poison_message_is_skipped_not_deleted_and_loop_survives(monkeypatch):
    done = []

    async def fake_process(received, queue, blobs):
        done.append(received.receipt)

    monkeypatch.setattr(worker_loop, "process_message", fake_process)
    q = ScriptedQueue([[ReceivedMessage("bad", 1, None), ReceivedMessage("ok", 1, msg(1))]])
    worker = Worker(q, object(), concurrency=2, wait_seconds=0)
    await run_until(worker, lambda: done == ["ok"])
    assert q.deleted == [] and q.visibility == []


async def test_unhandled_processing_error_does_not_kill_worker(monkeypatch):
    seen = []

    async def fake_process(received, queue, blobs):
        seen.append(received.receipt)
        if received.receipt == "boom":
            raise RuntimeError("db exploded with secret text")

    monkeypatch.setattr(worker_loop, "process_message", fake_process)
    q = ScriptedQueue([[ReceivedMessage("boom", 1, msg(1))], [ReceivedMessage("after", 1, msg(2))]])
    worker = Worker(q, object(), concurrency=1, wait_seconds=0)
    await run_until(worker, lambda: "after" in seen)
    assert seen == ["boom", "after"]


async def test_receive_errors_back_off_and_flip_readiness(monkeypatch):
    class Broken:
        def receive(self, n, wait):
            raise RuntimeError("no network")

    async def instant(self, seconds):
        await asyncio.sleep(0)

    monkeypatch.setattr(Worker, "_sleep", instant)
    worker = Worker(Broken(), object(), concurrency=1, wait_seconds=0)
    worker.warm = True
    assert worker.ready
    await run_until(worker, lambda: worker.poll_errors >= 5)
    assert worker.poll_errors >= 5


async def test_messages_received_after_stop_are_released_not_started(monkeypatch):
    started = []

    async def fake_process(received, queue, blobs):
        started.append(received.receipt)

    monkeypatch.setattr(worker_loop, "process_message", fake_process)

    class StopDuringPoll(ScriptedQueue):
        def receive(self, n, wait):
            worker.stop()  # SIGTERM lands while the long poll is in flight
            return [ReceivedMessage("late", 1, msg(1))]

    q = StopDuringPoll([])
    worker = Worker(q, object(), concurrency=1, wait_seconds=0)
    await asyncio.wait_for(worker.run(), 5)
    assert started == [] and q.visibility == [("late", 0)]


async def test_graceful_shutdown_lets_short_job_finish(monkeypatch):
    finished = []

    async def fake_process(received, queue, blobs):
        await asyncio.sleep(0.2)
        finished.append(received.receipt)

    monkeypatch.setattr(worker_loop, "process_message", fake_process)
    q = ScriptedQueue([[ReceivedMessage("r1", 1, msg(1))]])
    worker = Worker(q, object(), concurrency=1, wait_seconds=0, shutdown_timeout=5)
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.1)
    worker.stop()
    await asyncio.wait_for(task, 5)
    assert finished == ["r1"]


async def test_shutdown_deadline_cancels_stuck_job_so_it_can_release_its_message(monkeypatch):
    cancelled = []

    async def fake_process(received, queue, blobs):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.append(received.receipt)  # real process_message releases the message here
            raise

    monkeypatch.setattr(worker_loop, "process_message", fake_process)
    q = ScriptedQueue([[ReceivedMessage("r1", 1, msg(1))]])
    worker = Worker(q, object(), concurrency=1, wait_seconds=0, shutdown_timeout=0.2)
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.1)
    worker.stop()
    await asyncio.wait_for(task, 5)
    assert cancelled == ["r1"]


def get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


def test_probe_server_liveness_readiness_and_metrics():
    class FakeWorker:
        alive, ready = True, False

    w = FakeWorker()
    server = make_server(w, 0, host="127.0.0.1")
    serve_in_thread(server)
    port = server.server_address[1]
    try:
        assert get(port, "/livez")[0] == 200
        assert get(port, "/readyz")[0] == 503
        w.ready = True
        assert get(port, "/readyz")[0] == 200
        w.alive = False
        assert get(port, "/livez")[0] == 503
        code, body = get(port, "/metrics")
        assert code == 200 and "docchat_ingest_jobs_total" in body
        assert get(port, "/unknown")[0] == 404
    finally:
        server.shutdown()


def test_worker_liveness_goes_stale_when_loop_stops_ticking(monkeypatch):
    w = Worker(object(), object())
    assert w.alive
    w._tick -= 120
    assert not w.alive


def test_ingest_event_updates_metrics_with_bounded_labels():
    before = metrics.ingest_jobs.labels("web", "done")._value.get()
    metrics.observe({"event": "ingest_job", "source_type": "web", "outcome": "done", "duration_s": 0.5})
    metrics.observe({"event": "ingest_job", "source_type": "https://evil.test/x", "outcome": "weird", "duration_s": 1})
    assert metrics.ingest_jobs.labels("web", "done")._value.get() == before + 1
    assert metrics.ingest_jobs.labels("other", "other")._value.get() >= 1
    from prometheus_client import generate_latest
    assert b"evil.test" not in generate_latest(metrics.registry)


@pytest.mark.parametrize("path", ["/api/v1/health/live"])
def test_api_liveness_needs_no_dependencies(path):
    from fastapi.testclient import TestClient
    from app.main import app
    r = TestClient(app).get(path)
    assert r.status_code == 200 and r.json() == {"status": "ok"}


# ---------- ECS task scale-in protection ----------
from app.worker.protection import TaskProtection  # noqa: E402


class FakeAgent:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, url, body):
        if self.fail:
            raise OSError("agent down http://169.254.170.2/secret")
        self.calls.append((url, dict(body)))


async def test_protection_on_for_first_job_off_after_last():
    agent = FakeAgent()
    p = TaskProtection("http://agent/", send=agent)
    await p.job_started()
    await p.job_started()  # second job: no extra call
    await p.job_finished()
    assert [c[1]["ProtectionEnabled"] for c in agent.calls] == [True]
    await p.job_finished()
    assert [c[1]["ProtectionEnabled"] for c in agent.calls] == [True, False]
    assert agent.calls[0][0] == "http://agent/task-protection/v1/state"
    assert agent.calls[0][1]["ExpiresInMinutes"] == 5 and "ExpiresInMinutes" not in agent.calls[1][1]


async def test_protection_renews_only_while_busy():
    agent = FakeAgent()
    p = TaskProtection("http://agent", send=agent)
    await p.renew()
    assert agent.calls == []
    await p.job_started()
    await p.renew()
    assert len(agent.calls) == 2


async def test_protection_fails_safe_and_logs_once_without_error_text(caplog):
    p = TaskProtection("http://agent", send=FakeAgent(fail=True))
    with caplog.at_level("WARNING", logger="worker"):
        await p.job_started()
        await p.renew()
        await p.job_finished()
    assert caplog.text.count("task_protection_unavailable") == 1
    assert "169.254" not in caplog.text and "secret" not in caplog.text


async def test_protection_is_a_no_op_without_the_agent_endpoint(monkeypatch):
    monkeypatch.delenv("ECS_AGENT_URI", raising=False)
    agent = FakeAgent()
    p = TaskProtection(send=agent)
    await p.job_started()
    await p.job_finished()
    assert agent.calls == [] and p.url is None


async def test_worker_protects_while_a_job_runs_and_releases_after(monkeypatch):
    agent = FakeAgent()
    release = asyncio.Event()
    seen = []

    async def fake_process(received, queue, blobs):
        seen.append(len(agent.calls))
        await release.wait()

    monkeypatch.setattr(worker_loop, "process_message", fake_process)
    q = ScriptedQueue([[ReceivedMessage("r1", 1, msg(1))]])
    w = Worker(q, object(), concurrency=1, wait_seconds=0, protection=TaskProtection("http://a", send=agent))
    task = asyncio.create_task(w.run())
    for _ in range(200):
        if seen:
            break
        await asyncio.sleep(0.01)
    assert seen == [1] and agent.calls[0][1]["ProtectionEnabled"] is True
    release.set()
    for _ in range(200):
        if len(agent.calls) == 2:
            break
        await asyncio.sleep(0.01)
    w.stop()
    await asyncio.wait_for(task, 5)
    assert [c[1]["ProtectionEnabled"] for c in agent.calls] == [True, False]


async def test_cancelled_job_still_releases_protection(monkeypatch):
    agent = FakeAgent()

    async def hang(received, queue, blobs):
        await asyncio.sleep(60)

    monkeypatch.setattr(worker_loop, "process_message", hang)
    q = ScriptedQueue([[ReceivedMessage("r1", 1, msg(1))]])
    w = Worker(q, object(), concurrency=1, wait_seconds=0, shutdown_timeout=0.1,
               protection=TaskProtection("http://a", send=agent))
    task = asyncio.create_task(w.run())
    await asyncio.sleep(0.1)
    w.stop()
    await asyncio.wait_for(task, 5)
    assert [c[1]["ProtectionEnabled"] for c in agent.calls] == [True, False]
