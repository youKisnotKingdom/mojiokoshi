from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "Mojiokoshi"
    debug: bool = False
    secret_key: str
    allowed_hosts: str = "localhost,127.0.0.1,::1"

    @model_validator(mode="after")
    def validate_secret_key(self) -> "Settings":
        if not self.secret_key or self.secret_key == _INSECURE_DEFAULT:
            raise ValueError(
                "SECRET_KEY must be set to a secure random value. "
                "Run: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return self

    # Database
    database_url: str = "postgresql://mojiokoshi:mojiokoshi@localhost:5432/mojiokoshi"

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
    whisper_model_size: str = "medium"
    whisper_device: str = "cpu"
    whisper_language: str = "ja"
    default_transcription_engine: str = "parakeet_ja"
    parakeet_chunk_seconds: int = 300
    parakeet_sample_rate: int = 16000
    enable_realtime_transcription: bool = True
    worker_poll_interval: float = 5.0
    worker_transcription_concurrency: int = 1
    worker_summary_concurrency: int = 1
    worker_transcription_stale_timeout_seconds: int = 3600
    worker_summary_stale_timeout_seconds: int = 1800


@lru_cache
def get_settings() -> Settings:
    return Settings()
