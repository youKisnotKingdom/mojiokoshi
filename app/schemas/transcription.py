import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.transcription import (
    SpeakerDiarizationStatus,
    TranscriptionEngine,
    TranscriptionStatus,
)
from app.schemas.audio import AudioFileResponse


class TranscriptionJobCreate(BaseModel):
    audio_file_id: uuid.UUID
    engine: TranscriptionEngine = TranscriptionEngine.PARAKEET_JA
    model_size: str = "parakeet-tdt_ctc-0.6b-ja"
    language: str | None = None
    enable_speaker_diarization: bool = False


class TranscriptionJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    audio_file_id: uuid.UUID
    user_id: int
    status: TranscriptionStatus
    engine: TranscriptionEngine
    model_size: str
    language: str | None
    enable_speaker_diarization: bool
    speaker_diarization_status: SpeakerDiarizationStatus
    speaker_diarization_error: str | None
    speaker_diarization_started_at: datetime | None
    speaker_diarization_completed_at: datetime | None
    result_text: str | None
    progress_percent: float
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    is_complete: bool
    is_failed: bool
    duration_display: str


class TranscriptionJobDetail(TranscriptionJobResponse):
    model_config = ConfigDict(from_attributes=True)

    audio_file: AudioFileResponse
    result_segments: dict | None = None


class TranscriptionProgressResponse(BaseModel):
    id: uuid.UUID
    status: TranscriptionStatus
    progress_percent: float
    error_message: str | None
