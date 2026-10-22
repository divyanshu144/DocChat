"""Logging setup: optional one-line JSON, correlation id on every line, secrets and content scrubbed.

Defence in depth on top of app/core/telemetry.py (which already emits content-free records):
this layer also covers ad-hoc log calls, exception text and third-party libraries.
Exception messages and tracebacks are reduced to type + location because that text is where
document content, URLs and credentials most often leak.
"""
import json
import logging
import re
import sys
import traceback
from datetime import datetime, timezone

from app.core.config import settings

REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(
    r"(authorization|token|secret|password|passwd|api[_-]?key|cookie|credential|prompt|content|"
    r"text|query|body|url|file[_-]?name|answer|question|transcript|email)", re.I)
_PATTERNS = [
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer " + REDACTED),
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"), REDACTED),  # JWT
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), REDACTED),                              # AWS key id
    (re.compile(r"\b(?:gsk|sk|xox[bp]|ghp|glpat)[-_][A-Za-z0-9_-]{16,}"), REDACTED),         # provider keys
    (re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|authorization)\s*[=:]\s*\S+"),
     r"\1=" + REDACTED),
    (re.compile(r"(https?://)[^\s/@]+@"), r"\1" + REDACTED + "@"),                           # URL userinfo
    (re.compile(r"(https?://[^\s?#\"']+)[?#][^\s\"']*"), r"\1?" + REDACTED),                 # URL query
]
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime", "taskName"}


def scrub(value: str) -> str:
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def redact(value, key: str = ""):
    """Recursively scrub. Numbers/bools/None under a sensitive key are kept (e.g. prompt_tokens=12)."""
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, key) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if _SENSITIVE_KEY.search(key):
        return REDACTED
    return scrub(str(value))


def _location(exc_info) -> str | None:
    frames = traceback.extract_tb(exc_info[2])
    if not frames:
        return None
    last = frames[-1]
    return f"{last.filename.rsplit('/', 1)[-1]}:{last.lineno}:{last.name}"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        from app.core.telemetry import request_id

        message = record.getMessage()
        fields: dict = {}
        if message.startswith("{"):  # telemetry.emit() logs a JSON object as the message
            try:
                parsed = json.loads(message)
                if isinstance(parsed, dict):
                    message, fields = str(parsed.pop("event", "event")), parsed
            except ValueError:
                pass
        for key, value in record.__dict__.items():
            if key not in _STANDARD:
                fields[key] = value
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname, "logger": record.name,
            "message": scrub(message), "env": settings.environment,
        }
        rid = fields.pop("request_id", None) or request_id()
        if rid:
            entry["request_id"] = rid
        if record.exc_info and record.exc_info[0]:
            entry["exc_type"] = record.exc_info[0].__name__
            entry["exc_where"] = _location(record.exc_info)
        entry.update(redact(fields))
        return json.dumps(entry, separators=(",", ":"), default=str)


class ScrubbingTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return scrub(super().format(record))


# These log every outbound request at INFO, including user-supplied URLs (ingest sources).
_CHATTY_LIBRARIES = ("httpx", "httpcore", "urllib3", "botocore", "boto3", "s3transfer")


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout if settings.log_format == "json" else None)
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ScrubbingTextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in _CHATTY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
    if settings.log_format == "json":
        # Route uvicorn's own records through the same formatter; its access log carries query strings.
        for name in ("uvicorn", "uvicorn.error"):
            logging.getLogger(name).handlers.clear()
            logging.getLogger(name).propagate = True
        logging.getLogger("uvicorn.access").disabled = True
