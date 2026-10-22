from pathlib import Path
from functools import lru_cache
from typing import Literal
from urllib.parse import quote
from pydantic import Field, model_validator

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_JWT_SECRET_KEY = "change-me-in-production-use-a-long-random-string"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_PROJECT_ROOT / ".env"), extra="ignore")

    app_name: str = "DocChat Agent"
    version: str = "2.0.0"
    debug: bool = False

    api_prefix: str = "/api/v1"
    metrics_bearer_token: str = ""
    # Override via DATABASE_URL in .env for production
    database_url: str = "postgresql+asyncpg://docchat:docchat@localhost:5432/docchat"

    # LLM
    # Which backend `app.services.llm` talks to. Per-provider model names are kept
    # separate so switching providers is a one-variable change, not two.
    llm_provider: Literal["groq", "mistral", "openai", "local"] = "groq"
    fallback_llm_provider: Literal["none", "openai"] = "openai"

    groq_api_key: str = ""
    # Used when llm_provider="groq". Was llama-3.3-70b-versatile, which Groq has since
    # decommissioned — it now 404s with model_not_found, so the whole Groq path was
    # dead on defaults. Verify against GET /models before changing.
    chat_model: str = "openai/gpt-oss-120b"
    groq_fallback_chat_model: str = ""

    openai_api_key: str = ""
    # Eval-only: used by eval/judge_answer_review_pack.py for the Claude judge; not a chat provider.
    anthropic_api_key: str = ""
    openai_chat_model: str = "gpt-5.6-luna"  # used when llm_provider="openai"
    # Blank preserves the model default. Short classification evals can select
    # none on compatible models so hidden reasoning does not consume their cap.
    openai_reasoning_effort: Literal["", "none", "low", "medium", "high", "xhigh"] = ""

    mistral_api_key: str = ""
    mistral_chat_model: str = "mistral-small-latest"  # used when llm_provider="mistral"

    # Self-hosted inference (e.g. vLLM serving an open-weight model on a rented GPU).
    # Benchmarking target, not a reliability path — deliberately excluded from the
    # Groq->OpenAI fallback chain, since the box may not be running. Blank base URL
    # means the provider is unconfigured; used only when llm_provider="local".
    local_base_url: str = ""
    local_chat_model: str = ""
    local_api_key: str = ""
    local_stream_completions: bool = False
    inference_connect_timeout_s: float = Field(default=5.0, gt=0)
    inference_read_timeout_s: float = Field(default=60.0, gt=0)
    inference_pool_timeout_s: float = Field(default=5.0, gt=0)
    inference_max_connections: int = Field(default=100, ge=1)

    chat_history_limit: int = 10

    # Embeddings
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    # Optional. Blank (the local default) sends no key. In AWS the key is injected from Secrets Manager.
    qdrant_api_key: str = ""

    # Retrieval quality gate — chunks below this cosine similarity score are dropped
    retrieval_min_score: float = 0.3
    context_max_chars: int = 12000
    ingest_batch_size: int = Field(default=64, ge=1)
    upload_max_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    login_rate_limit: int = Field(default=10, ge=1)
    signup_rate_limit: int = Field(default=5, ge=1)
    chat_rate_limit: int = Field(default=30, ge=1)

    # Sampling temperature for the nodes whose output is a LABEL rather than prose
    # (critic, planner). Pinned to 0 so a verdict does not move between identical
    # runs: at N=5 a single flip moved benchmark precision ~8 points, which exceeded
    # the effect anyone was trying to measure. The synthesizer is deliberately NOT
    # pinned — determinism buys nothing for prose and costs variety.
    #
    # NOT ALWAYS HONOURED: a model may reject an explicit temperature (gpt-5.6-luna
    # 400s on anything but the default). `llm.py` drops it and retries, so the request
    # succeeds but the pin is a no-op and verdicts still move between runs.
    classification_temperature: float = 0.0

    # Where the critic appends answers it rejected, as JSONL. Blank disables the
    # sink entirely; set it to ./data/critic_rejections.jsonl to start collecting.
    # These drafts exist nowhere else — the replan overwrites them in place.
    critic_rejection_log: str = ""

    # LangSmith observability. Tracing needs BOTH a key and the flag; the flag
    # exists so `LANGSMITH_TRACING=false` can silence a noisy eval or benchmark
    # run without anyone having to pull the key out of .env and forget to restore it.
    langsmith_api_key: str = ""
    langsmith_project: str = "docchat-agent"
    langsmith_tracing: bool = True
    # The SDK defaults to the US host. An EU-region key authenticates ONLY against
    # the EU host and 403s against US — which looks identical to a revoked key, so
    # set this explicitly rather than debugging it twice.
    langsmith_endpoint: str = ""

    # DB connection pool (PostgreSQL only)
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # JWT Authentication
    jwt_secret_key: str = _DEFAULT_JWT_SECRET_KEY
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # --- Cloud platform (all defaults keep the local, no-AWS behaviour) ---
    environment: Literal["local", "dev", "staging", "prod"] = "local"
    # "json" emits one redacted JSON object per line (CloudWatch); "text" is the local default.
    log_format: Literal["text", "json"] = "text"

    # Database as parts. When DATABASE_HOST is set, database_url is assembled from them, so
    # the RDS-managed secret can be injected as DATABASE_PASSWORD without a URL in Terraform state.
    database_host: str = ""
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "docchat"
    database_user: str = "docchat"
    database_password: str = ""
    # AWS mode: read the password from this Secrets Manager secret each time a connection is opened
    # (it rotates). Mutually exclusive with DATABASE_PASSWORD, which stays the local-development path.
    database_password_secret_arn: str = ""
    database_ssl: Literal["", "require"] = ""
    # Only one task may run DDL at a time; AWS API tasks serialise on an advisory lock,
    # workers never run DDL.
    run_migrations_on_startup: bool = True

    # Document storage and ingestion queue. "local" = this repo's original behaviour.
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_dir: str = str(_PROJECT_ROOT / "data" / "storage")
    s3_bucket: str = ""
    s3_prefix: str = "uploads/"
    aws_region: str = ""
    # Keep uploaded originals after a successful ingest. Required for DLQ redrive/re-ingest.
    retain_uploads: bool = False

    queue_backend: Literal["local", "sqs"] = "local"
    sqs_queue_url: str = ""
    sqs_wait_seconds: int = Field(default=20, ge=0, le=20)
    sqs_visibility_timeout_s: int = Field(default=300, ge=30)
    # Must equal the queue's redrive maxReceiveCount (Terraform sets both from one variable).
    ingest_max_attempts: int = Field(default=3, ge=1, le=20)
    ingest_retry_base_delay_s: int = Field(default=15, ge=1)
    ingest_retry_max_delay_s: int = Field(default=600, ge=1)
    ingest_job_timeout_s: int = Field(default=1800, ge=30)
    # An identical queued/running job younger than this is returned instead of enqueuing another.
    ingest_dedupe_window_s: int = Field(default=3600, ge=0)
    # A job still "queued" and untouched for this long is treated as dead for dedupe, so one stale row can
    # never block a fresh submission of the same source.
    ingest_queued_stale_s: int = Field(default=600, ge=1)

    # SSRF guard for web ingestion (see app/core/url_safety.py). Off locally so localhost docs still
    # work; required in staging/prod because the cloud worker has credentials a fetched URL could reach.
    ingest_block_private_urls: bool = False
    # Limits for guarded fetches (apply when the guard above is on): largest accepted response body after
    # decompression, and the total time for all redirects plus reading the body.
    web_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    web_fetch_timeout_s: float = Field(default=30.0, gt=0)

    worker_concurrency: int = Field(default=2, ge=1, le=32)
    worker_shutdown_timeout_s: int = Field(default=90, ge=1)
    worker_http_port: int = Field(default=8080, ge=1, le=65535)

    @model_validator(mode="after")
    def _validate_platform(self):
        if self.database_host:
            if "database_url" in self.model_fields_set:
                raise ValueError("Set either DATABASE_URL or DATABASE_HOST, not both")
            if self.database_password and self.database_password_secret_arn:
                raise ValueError("Set either DATABASE_PASSWORD or DATABASE_PASSWORD_SECRET_ARN, not both")
            if not self.database_password and not self.database_password_secret_arn:
                raise ValueError("DATABASE_PASSWORD (or DATABASE_PASSWORD_SECRET_ARN) is required "
                                 "when DATABASE_HOST is set")
            query = f"?ssl={self.database_ssl}" if self.database_ssl else ""
            secret = f":{quote(self.database_password, safe='')}" if self.database_password else ""
            self.database_url = (
                f"postgresql+asyncpg://{quote(self.database_user, safe='')}{secret}"
                f"@{self.database_host}:{self.database_port}/{self.database_name}{query}"
            )
        elif self.database_password_secret_arn:
            raise ValueError("DATABASE_PASSWORD_SECRET_ARN needs DATABASE_HOST")
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise ValueError("S3_BUCKET is required when STORAGE_BACKEND=s3")
        if self.queue_backend == "sqs":
            if not self.sqs_queue_url:
                raise ValueError("SQS_QUEUE_URL is required when QUEUE_BACKEND=sqs")
            if self.storage_backend != "s3":
                # API and worker tasks do not share a filesystem.
                raise ValueError("QUEUE_BACKEND=sqs requires STORAGE_BACKEND=s3")
        if self.ingest_retry_max_delay_s < self.ingest_retry_base_delay_s:
            raise ValueError("INGEST_RETRY_MAX_DELAY_S must be >= INGEST_RETRY_BASE_DELAY_S")
        if self.environment in ("staging", "prod"):
            if self.debug:
                raise ValueError("DEBUG must be false in staging/prod")
            # JWT_SECRET_KEY is enforced at API startup (app.main); the worker never receives it.
            if not self.ingest_block_private_urls:
                raise ValueError("INGEST_BLOCK_PRIVATE_URLS must be true in staging/prod")
        return self


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
