from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "Event Album API"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/event_album"
    DATABASE_SYNC_URL: Optional[str] = None

    # Cache & Tasks
    REDIS_URL: str = "redis://localhost:6379/0"

    # Cloudflare R2 (S3-compatible)
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "event-album"
    R2_ENDPOINT_URL: str = ""

    # App & Security
    DOMAIN: str = "yourdomain.com"
    SECRET_KEY: str = "insecure-secret-key-change-me"
    MATCH_THRESHOLD: float = 0.50

    # Concurrency & Performance
    CELERY_CONCURRENCY: Optional[int] = None
    OPENCV_NUM_THREADS: int = 2
    TOP_N_MATCHES: int = 50
    DETECTION_MAX_EDGE: int = 1280

    # Face Model Metadata (protects future swaps)
    MODEL_NAME: str = "sface"
    MODEL_VERSION: str = "2021dec"
    EMBEDDING_DIM: int = 128


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
