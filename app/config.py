from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "Mojiokoshi"
    debug: bool = False
    secret_key: str = "change-me-in-production"

    # Database
    database_url: str = "postgresql://mojiokoshi:mojiokoshi@localhost:5432/mojiokoshi"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Storage
    upload_dir: Path = Path("uploads")
    max_upload_size: int = 500 * 1024 * 1024  # 500MB

    # Audio cleanup
    audio_retention_days: int = 30

    # LLM API (local network server)
    llm_api_base_url: str = "http://localhost:8000/v1"
    llm_api_key: str = ""
    llm_model_name: str = "default"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.7
    llm_timeout: int = 120

    # Transcription
    whisper_model_size: str = "large"
    whisper_device: str = "cuda"


@lru_cache
def get_settings() -> Settings:
    return Settings()
