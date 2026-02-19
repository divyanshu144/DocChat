from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    """Application configuration settings loaded from environment variables or .env file."""

    app_name: str = "DocChat"
    version: str = "0.1.0"
    debug: bool = True


    # API
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./docchat.db"

    # File upload
    upload_dir: str = "./uploads"
    max_upload_bytes: int = 10_485_760  # 10 MB

    # Chat
    anthropic_api_key: str
    chat_history_limit: int = 10
    retrieval_top_k: int = 3

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings() -> Settings:
    """Get the application settings, cached for performance."""
    
    return Settings()


settings = get_settings()