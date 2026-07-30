from pathlib import Path
from functools import lru_cache
from typing import Literal

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
    llm_provider: Literal["groq", "mistral", "openai"] = "groq"
    fallback_llm_provider: Literal["none", "openai"] = "openai"

    groq_api_key: str = ""
    chat_model: str = "llama-3.3-70b-versatile"   # used when llm_provider="groq"
    groq_fallback_chat_model: str = ""

    openai_api_key: str = ""
    openai_chat_model: str = "gpt-5.6-luna"  # used when llm_provider="openai"

    mistral_api_key: str = ""
    mistral_chat_model: str = "mistral-small-latest"  # used when llm_provider="mistral"

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

    # LangSmith observability
    langsmith_api_key: str = ""
    langsmith_project: str = "docchat-agent"

    # YouTube (optional)
    youtube_api_key: str = ""

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
