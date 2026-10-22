import json
import logging

import pytest

from app.core import logging_config as lc
from app.core.config import settings
from app.core.telemetry import emit, request_trace

SECRETS = [
    "Bearer abc.def.ghi-123", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig123456",
    "AKIAIOSFODNN7EXAMPLE", "gsk_abcdefghijklmnopqrstuvwxyz", "sk-proj-abcdefghijklmnopqrstuv",
    "hunter2-password",
]


def render(monkeypatch, fn, fmt="json"):
    monkeypatch.setattr(settings, "log_format", fmt)
    handler_stream = []

    class Capture(logging.Handler):
        def emit(self, record):
            handler_stream.append(self.format(record))

    handler = Capture()
    handler.setFormatter(lc.JsonFormatter() if fmt == "json" else lc.ScrubbingTextFormatter("%(message)s"))
    log = logging.getLogger("t")
    telemetry = logging.getLogger("app.core.telemetry")  # emit() logs here
    saved = telemetry.handlers[:], telemetry.propagate
    for target in (log, telemetry):
        target.handlers, target.propagate, target.level = [handler], False, logging.INFO
    try:
        fn(log)
    finally:
        telemetry.handlers, telemetry.propagate = saved
    return handler_stream


def test_secrets_in_messages_are_scrubbed(monkeypatch):
    out = render(monkeypatch, lambda log: log.info(
        "auth header Authorization: %s key=%s password=%s url https://u:p@h.test/p?token=zzz&x=1",
        SECRETS[0], SECRETS[3], SECRETS[5]))[0]
    for secret in SECRETS[:1] + SECRETS[3:4] + SECRETS[5:] + ["u:p@", "token=zzz"]:
        assert secret not in out
    assert json.loads(out)["level"] == "INFO"


@pytest.mark.parametrize("secret", SECRETS[:5])
def test_token_shapes_scrubbed_anywhere(secret):
    assert secret not in lc.scrub(f"prefix {secret} suffix")


def test_sensitive_keys_redacted_but_numeric_token_counts_kept(monkeypatch):
    out = json.loads(render(monkeypatch, lambda log: log.info(
        "x", extra={"prompt": "tell me about X", "document_text": "SECRET BODY", "authorization": "Bearer q",
                    "url": "https://a.test/b", "file_name": "taxes.pdf", "prompt_tokens": 12, "route": "/chat"}))[0])
    assert out["prompt"] == out["document_text"] == out["authorization"] == out["url"] == lc.REDACTED
    assert out["file_name"] == lc.REDACTED
    assert out["prompt_tokens"] == 12 and out["route"] == "/chat"
    assert "SECRET BODY" not in json.dumps(out) and "taxes" not in json.dumps(out)


def test_exception_text_never_logged_only_type_and_location(monkeypatch):
    def fn(log):
        try:
            raise ValueError("document says: my password is hunter2")
        except ValueError:
            log.exception("failed")

    entry = json.loads(render(monkeypatch, fn)[0])
    assert entry["exc_type"] == "ValueError" and "test_logging_redaction.py" in entry["exc_where"]
    assert "hunter2" not in json.dumps(entry)


def test_request_id_attached_and_telemetry_json_is_flattened(monkeypatch):
    def fn(log):
        with request_trace("req-abc"):
            log.info("inside")
            emit({"event": "span", "name": "retriever", "prompt": "do not log me", "duration_s": 0.1})

    lines = [json.loads(x) for x in render(monkeypatch, fn)]
    assert all(line.get("request_id") == "req-abc" for line in lines)
    span = next(line for line in lines if line["message"] == "span")
    assert span["name"] == "retriever" and span["prompt"] == lc.REDACTED and "do not log me" not in json.dumps(span)


def test_text_mode_also_scrubs(monkeypatch):
    out = render(monkeypatch, lambda log: log.info("hdr %s", SECRETS[0]), fmt="text")[0]
    assert "abc.def.ghi" not in out


def test_configure_logging_is_idempotent_and_json_mode_silences_access_log(monkeypatch):
    monkeypatch.setattr(settings, "log_format", "json")
    root = logging.getLogger()
    saved = root.handlers[:]
    try:
        lc.configure_logging()
        lc.configure_logging()
        assert len(root.handlers) == 1 and isinstance(root.handlers[0].formatter, lc.JsonFormatter)
        assert logging.getLogger("uvicorn.access").disabled
    finally:
        logging.getLogger("uvicorn.access").disabled = False
        root.handlers[:] = saved


def test_http_client_libraries_cannot_log_ingested_urls(monkeypatch):
    """httpx logs 'HTTP Request: GET <full url>' at INFO; user-supplied URLs must not reach the logs."""
    root = logging.getLogger()
    saved = root.handlers[:]
    try:
        for fmt in ("json", "text"):
            monkeypatch.setattr(settings, "log_format", fmt)
            lc.configure_logging()
            for name in ("httpx", "httpcore", "urllib3", "botocore"):
                assert not logging.getLogger(name).isEnabledFor(logging.INFO), name
    finally:
        logging.getLogger("uvicorn.access").disabled = False
        root.handlers[:] = saved
        for name in lc._CHATTY_LIBRARIES:
            logging.getLogger(name).setLevel(logging.NOTSET)
