from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application configuration settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(env_file=str(_PROJECT_ROOT / ".env"))

    app_name: str = "DocChat"
    version: str = "0.1.0"
    debug: bool = True

    # API
    api_prefix: str = "/api/v1"
    database_url: str = f"sqlite+aiosqlite:///{_PROJECT_ROOT / 'docchat.db'}"

    # File upload
    upload_dir: str = str(_PROJECT_ROOT / "uploads")
    max_upload_bytes: int = 10_485_760  # 10 MB

    # Chat
    anthropic_api_key: str
    chat_history_limit: int = 10
    retrieval_top_k: int = 3


@lru_cache()
def get_settings() -> Settings:
    """Get the application settings, cached for performance."""
    return Settings()


settings = get_settings()
