import json

import pytest

from app.services import queueing
from app.services.queueing import IngestMessage, MessageError, backoff_seconds
from app.services.queueing.sqs import SQSQueue


class FakeSQS:
    def __init__(self):
        self.sent, self.deleted, self.visibility, self.pending = [], [], [], []

    def send_message(self, QueueUrl, MessageBody):
        self.sent.append((QueueUrl, MessageBody))

    def receive_message(self, **kw):
        self.last_receive = kw
        out, self.pending = self.pending, []
        return {"Messages": out}

    def delete_message(self, QueueUrl, ReceiptHandle):
        self.deleted.append(ReceiptHandle)

    def change_message_visibility(self, QueueUrl, ReceiptHandle, VisibilityTimeout):
        self.visibility.append((ReceiptHandle, VisibilityTimeout))


def pdf_msg(**kw):
    return IngestMessage(job_id="j1", source_type="pdf", storage_key="uploads/j1/source.pdf",
                         filename="a.pdf", content_type="application/pdf", correlation_id="rid", **kw)


def test_roundtrip():
    m = pdf_msg()
    assert IngestMessage.from_body(m.to_body()) == m


@pytest.mark.parametrize("body", [
    "not json", "[]", json.dumps({"v": 2, "job_id": "a", "source_type": "pdf"}),
    json.dumps({"v": 1, "job_id": "bad id!", "source_type": "pdf", "storage_key": "k"}),
    json.dumps({"v": 1, "job_id": "a", "source_type": "docx", "storage_key": "k"}),
    json.dumps({"v": 1, "job_id": "a", "source_type": "pdf"}),
    json.dumps({"v": 1, "job_id": "a", "source_type": "web"}),
    json.dumps({"v": 1, "job_id": "a", "source_type": "web", "url": 5}),
])
def test_invalid_bodies_rejected_without_echo(body):
    with pytest.raises(MessageError) as err:
        IngestMessage.from_body(body)
    assert body not in str(err.value) or len(body) < 12


def test_send_and_receive_parse_poison_and_count():
    fake = FakeSQS()
    q = SQSQueue("https://sqs.test/q", client=fake)
    m = IngestMessage(job_id="j2", source_type="web", url="https://example.com/p")
    q.send(m)
    assert fake.sent == [("https://sqs.test/q", m.to_body())]
    fake.pending = [
        {"ReceiptHandle": "r1", "Body": m.to_body(), "Attributes": {"ApproximateReceiveCount": "3"}},
        {"ReceiptHandle": "r2", "Body": "garbage"},
    ]
    got = q.receive(50, 99)
    assert fake.last_receive["MaxNumberOfMessages"] == 10 and fake.last_receive["WaitTimeSeconds"] == 20
    assert (got[0].message, got[0].receive_count) == (m, 3)
    assert got[1].message is None and got[1].receive_count == 1


def test_delete_and_visibility_clamped():
    fake = FakeSQS()
    q = SQSQueue("u", client=fake)
    q.delete("r")
    q.change_visibility("r", -5)
    q.change_visibility("r", 10**9)
    assert fake.deleted == ["r"] and fake.visibility == [("r", 0), ("r", 43200)]


def test_backoff_doubles_then_caps(monkeypatch):
    monkeypatch.setattr(queueing.settings, "ingest_retry_base_delay_s", 15)
    monkeypatch.setattr(queueing.settings, "ingest_retry_max_delay_s", 100)
    assert [backoff_seconds(n) for n in (1, 2, 3, 4, 5)] == [15, 30, 60, 100, 100]


def test_get_queue_refuses_local_backend():
    queueing.get_queue.cache_clear()
    with pytest.raises(RuntimeError):
        queueing.get_queue()
