from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application configuration settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(env_file=str(_PROJECT_ROOT / ".env"))

    app_name: str = "DocChat"
    version: str = "0.1.0"
    debug: bool = False

    # API
    api_prefix: str = "/api/v1"
    database_url: str = f"sqlite+aiosqlite:///{_PROJECT_ROOT / 'docchat.db'}"

    # File upload
    upload_dir: str = str(_PROJECT_ROOT / "uploads")
    max_upload_bytes: int = 10_485_760  # 10 MB

    # Chat
    groq_api_key: str
    chat_model: str = "llama-3.3-70b-versatile"
    chat_history_limit: int = 10
    retrieval_top_k: int = 15

    # Re-ranking (FlashRank cross-encoder)
    rerank_enabled: bool = True
    rerank_top_k: int = 5          # chunks sent to LLM after re-ranking

    # HyDE — embed a hypothetical answer instead of the raw question
    hyde_enabled: bool = False     # opt-in; adds one LLM call per query

    # Semantic cache (requires REDIS_URL)
    semantic_cache_enabled: bool = False
    semantic_cache_threshold: float = 0.95

    # Conversation summarization — summarise history older than this many messages
    history_summary_threshold: int = 20

    # Embeddings
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # API key authentication (set to enable; leave unset to disable in dev)
    api_key: str | None = None

    # Optional background queue (ARQ) + Redis-backed caches
    redis_url: str | None = None

    # AWS S3 (optional — falls back to local disk when unset)
    s3_bucket: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "us-east-1"

    # DB connection pool (PostgreSQL only)
    db_pool_size: int = 10
    db_max_overflow: int = 20

    @property
    def use_s3(self) -> bool:
        return bool(self.s3_bucket)


@lru_cache()
def get_settings() -> Settings:
    """Get the application settings, cached for performance."""
    return Settings()


settings = get_settings()
