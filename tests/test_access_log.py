"""uvicorn's access log is off in JSON mode (it records query strings). This proves the request telemetry event
already covers method, route template, status, duration and request id, and never the query string or real ids."""
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.core import logging_config as lc
from app.main import app


@pytest.fixture
def request_events(caplog):
    caplog.set_level(logging.INFO, logger="app.core.telemetry")

    def fetch():
        events = []
        for record in caplog.records:
            if record.name == "app.core.telemetry" and record.getMessage().startswith("{"):
                data = json.loads(record.getMessage())
                if data.get("event") == "request":
                    events.append((record, data))
        return events

    return fetch


def test_request_event_has_the_access_log_fields_and_no_query_string(request_events):
    r = TestClient(app).get("/api/v1/health/live?token=SECRET123&email=a@b.test",
                            headers={"X-Request-ID": "req-abc"})
    assert r.status_code == 200 and r.headers["x-request-id"] == "req-abc"
    (record, event), = request_events()
    assert event["method"] == "GET" and event["status_code"] == 200
    assert event["route"].endswith("/health/live") and event["request_id"] == "req-abc"
    assert isinstance(event["duration_s"], float) and event["duration_s"] >= 0

    line = json.loads(lc.JsonFormatter().format(record))  # the JSON log line CloudWatch would receive
    for key in ("method", "route", "status_code", "duration_s", "request_id"):
        assert key in line, key
    assert line["message"] == "request"
    blob = json.dumps(line)
    assert "SECRET123" not in blob and "a@b.test" not in blob and "token=" not in blob


def test_route_is_the_template_not_the_real_id_and_errors_are_recorded(request_events):
    r = TestClient(app).get("/api/v1/ingest/jobs/real-job-id-9f8e7d?key=hunter2")
    assert r.status_code in (401, 403)
    (record, event), = request_events()
    assert "{job_id}" in event["route"] and "real-job-id" not in json.dumps(event)
    assert event["status_code"] == r.status_code and event["outcome"] == "error"
    assert "hunter2" not in json.dumps(json.loads(lc.JsonFormatter().format(record)))


def test_the_uvicorn_access_log_stays_disabled_in_json_mode(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "log_format", "json")
    root = logging.getLogger()
    saved = root.handlers[:]
    try:
        lc.configure_logging()
        assert logging.getLogger("uvicorn.access").disabled
    finally:
        logging.getLogger("uvicorn.access").disabled = False
        root.handlers[:] = saved
        for name in lc._CHATTY_LIBRARIES:
            logging.getLogger(name).setLevel(logging.NOTSET)
