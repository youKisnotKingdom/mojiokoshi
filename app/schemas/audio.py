import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.audio import AudioSource


class AudioFileBase(BaseModel):
    original_filename: str
    source: AudioSource = AudioSource.UPLOAD


class AudioFileCreate(AudioFileBase):
    pass


class AudioFileResponse(AudioFileBase):
    id: uuid.UUID
    user_id: int
    stored_filename: str
    file_size: int
    mime_type: str | None
    duration_seconds: float | None
    duration_display: str
    created_at: datetime
    expires_at: datetime | None
    is_deleted: bool

    class Config:
        from_attributes = True
