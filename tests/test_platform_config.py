"""Cloud settings: local defaults stay AWS-free, unsafe combinations are refused."""
import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make(**kw):
    return Settings(_env_file=None, **kw)


def test_defaults_need_no_aws():
    s = make()
    assert (s.storage_backend, s.queue_backend, s.environment) == ("local", "local", "local")
    assert s.log_format == "text" and s.run_migrations_on_startup is True
    assert s.database_url.startswith("postgresql+asyncpg://docchat:docchat@localhost")


def test_database_url_assembled_and_escaped():
    s = make(database_host="db.internal", database_user="u@x", database_password="p/w:#?",
             database_ssl="require")
    assert s.database_url == "postgresql+asyncpg://u%40x:p%2Fw%3A%23%3F@db.internal:5432/docchat?ssl=require"


def test_database_parts_need_password():
    with pytest.raises(ValidationError, match="DATABASE_PASSWORD"):
        make(database_host="db.internal")


def test_database_url_and_host_conflict():
    with pytest.raises(ValidationError, match="not both"):
        make(database_url="postgresql+asyncpg://a:b@h/d", database_host="h", database_password="x")


def test_s3_requires_bucket():
    with pytest.raises(ValidationError, match="S3_BUCKET"):
        make(storage_backend="s3")


def test_sqs_requires_url_and_s3():
    with pytest.raises(ValidationError, match="SQS_QUEUE_URL"):
        make(queue_backend="sqs", storage_backend="s3", s3_bucket="b")
    with pytest.raises(ValidationError, match="requires STORAGE_BACKEND=s3"):
        make(queue_backend="sqs", sqs_queue_url="https://sqs.example/q")
    ok = make(queue_backend="sqs", sqs_queue_url="https://sqs.example/q",
              storage_backend="s3", s3_bucket="b")
    assert ok.queue_backend == "sqs"


def test_retry_delay_ordering():
    with pytest.raises(ValidationError, match="RETRY_MAX"):
        make(ingest_retry_base_delay_s=60, ingest_retry_max_delay_s=30)


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_production_refuses_debug_and_unguarded_fetches(env):
    with pytest.raises(ValidationError, match="DEBUG"):
        make(environment=env, debug=True, ingest_block_private_urls=True)
    with pytest.raises(ValidationError, match="INGEST_BLOCK_PRIVATE_URLS"):
        make(environment=env)
    # No JWT secret needed: the worker never receives one; the API refuses the default at startup.
    assert make(environment=env, ingest_block_private_urls=True).environment == env
