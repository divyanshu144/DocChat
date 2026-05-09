from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_PROJECT_ROOT / ".env"))

    app_name: str = "DocChat Agent"
    version: str = "2.0.0"
    debug: bool = False

    api_prefix: str = "/api/v1"
    database_url: str = f"sqlite+aiosqlite:///{_PROJECT_ROOT / 'docchat.db'}"

    # LLM
    groq_api_key: str = ""
    chat_model: str = "llama-3.3-70b-versatile"
    chat_history_limit: int = 10

    # Embeddings
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # ChromaDB
    chroma_host: str = "localhost"
    chroma_port: int = 8001

    # LangSmith observability
    langsmith_api_key: str = ""
    langsmith_project: str = "docchat-agent"

    # YouTube (optional)
    youtube_api_key: str = ""

    # DB connection pool (PostgreSQL only)
    db_pool_size: int = 10
    db_max_overflow: int = 20


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
