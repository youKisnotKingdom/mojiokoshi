import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TranscriptionStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TranscriptionEngine(str, enum.Enum):
    WHISPER = "whisper"
    FASTER_WHISPER = "faster_whisper"
    QWEN_ASR = "qwen_asr"
    PARAKEET_JA = "parakeet_ja"


class TranscriptionJob(Base):
    __tablename__ = "transcription_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    audio_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audio_files.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    status: Mapped[TranscriptionStatus] = mapped_column(
        Enum(TranscriptionStatus), default=TranscriptionStatus.PENDING, nullable=False
    )
    engine: Mapped[TranscriptionEngine] = mapped_column(
        Enum(TranscriptionEngine), default=TranscriptionEngine.PARAKEET_JA, nullable=False
    )
    model_size: Mapped[str] = mapped_column(
        String(50), default="parakeet-tdt_ctc-0.6b-ja", nullable=False
    )
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)  # None = auto-detect

    # Results
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_segments: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Progress tracking
    progress_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    audio_file = relationship("AudioFile", back_populates="transcription_jobs")
    user = relationship("User", backref="transcription_jobs")
    summaries = relationship(
        "Summary", back_populates="transcription_job", cascade="all, delete-orphan"
    )

    @property
    def is_complete(self) -> bool:
        return self.status == TranscriptionStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == TranscriptionStatus.FAILED

    @property
    def duration_display(self) -> str:
        if not self.started_at or not self.completed_at:
            return "N/A"
        duration = (self.completed_at - self.started_at).total_seconds()
        return f"{duration:.1f}s"
