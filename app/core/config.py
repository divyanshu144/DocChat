from pathlib import Path
from functools import lru_cache
from typing import Literal
from pydantic import Field

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_PROJECT_ROOT / ".env"), extra="ignore")

    app_name: str = "DocChat Agent"
    version: str = "2.0.0"
    debug: bool = False

    api_prefix: str = "/api/v1"
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

    chat_history_limit: int = 10

    # Embeddings
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

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
    jwt_secret_key: str = "change-me-in-production-use-a-long-random-string"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
