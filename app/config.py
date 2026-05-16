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
    show_next_actions: bool = False

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

    # Authentication
    ldap_enabled: bool = False
    ldap_server_uri: str = ""
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_user_base_dn: str = ""
    ldap_user_filter: str = "(uid={username})"
    ldap_user_id_attribute: str = "uid"
    ldap_display_name_attribute: str = "cn"
    ldap_start_tls: bool = False
    ldap_connect_timeout: int = 5
    ldap_default_role: str = "user"
    ldap_bootstrap_admin_user_ids: str = ""
    local_password_login_enabled: bool = True
    ldap_group_base_dn: str = ""
    ldap_group_filter: str = "(member={user_dn})"
    ldap_admin_group_dn: str = ""

    # Storage
    upload_dir: Path = Path("uploads")
    max_upload_size: int = 500 * 1024 * 1024  # 500MB

    # Audio cleanup
    audio_retention_days: int = 30

    # LLM API (local network server)
    llm_api_base_url: str = "http://localhost:8000/v1"
    llm_api_key: str = ""
    llm_model_name: str = "default"
    llm_max_tokens: int = 8192
    llm_temperature: float = 0.7
    llm_timeout: int = 300
    chunk_refinement_llm_api_base_url: str = ""
    chunk_refinement_llm_api_key: str = ""
    chunk_refinement_llm_model_name: str = ""
    chunk_refinement_llm_temperature: float = 0.1
    chunk_refinement_llm_timeout: int = 0

    # Transcription
    whisper_model_size: str = "medium"
    whisper_device: str = "cpu"
    whisper_language: str = "ja"
    default_transcription_engine: str = "reazon_nemo_v2"
    cohere_transcribe_device: str = ""
    parakeet_chunk_seconds: int = 300
    parakeet_sample_rate: int = 16000
    audio_preprocessing_mode: str = "light"
    enable_speaker_diarization: bool = False
    speaker_diarization_model_id: str = "pyannote/speaker-diarization-community-1"
    speaker_diarization_model_path: str = ""
    speaker_diarization_device: str = "auto"
    speaker_diarization_min_speakers: int = 0
    speaker_diarization_max_speakers: int = 0
    huggingface_token: str = ""
    enable_realtime_transcription: bool = True
    worker_poll_interval: float = 5.0
    worker_transcription_concurrency: int = 1
    worker_chunk_refinement_concurrency: int = 1
    worker_summary_concurrency: int = 1
    worker_speaker_diarization_concurrency: int = 0
    worker_transcription_stale_timeout_seconds: int = 3600
    worker_chunk_refinement_stale_timeout_seconds: int = 1800
    worker_summary_stale_timeout_seconds: int = 1800
    worker_speaker_diarization_stale_timeout_seconds: int = 14400
    worker_cleanup_interval_seconds: int = 3600
    auto_llm_prompt_template_names: str = "文字起こし整形"
    enable_chunk_llm_refinement: bool = True
    llm_chunk_refinement_max_input_chars: int = 12000
    llm_chunk_refinement_max_output_tokens: int = 2000
    llm_chunk_refinement_context_chars: int = 1000


@lru_cache
def get_settings() -> Settings:
    return Settings()
