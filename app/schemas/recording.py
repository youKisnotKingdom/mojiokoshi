import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.recording import RecordingStatus


class RecordingSessionCreate(BaseModel):
    pass


class RecordingSessionResponse(BaseModel):
    id: uuid.UUID
    user_id: int
    status: RecordingStatus
    total_duration_seconds: float
    chunk_count: int
    audio_file_id: uuid.UUID | None
    created_at: datetime
    started_at: datetime
    paused_at: datetime | None
    completed_at: datetime | None

    class Config:
        from_attributes = True


class RecordingChunkResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    chunk_index: int
    file_size: int
    duration_seconds: float
    received_at: datetime

    class Config:
        from_attributes = True


# WebSocket message types
class WSMessage(BaseModel):
    type: str
    data: dict | None = None


class WSChunkReceived(BaseModel):
    type: str = "chunk_received"
    chunk_index: int
    total_duration: float


class WSTranscriptionResult(BaseModel):
    type: str = "transcription"
    text: str
    is_partial: bool = False
    segment_start: float | None = None
    segment_end: float | None = None


class WSError(BaseModel):
    type: str = "error"
    message: str
