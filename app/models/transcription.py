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
    UniqueConstraint,
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


class ChunkRefinementStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SpeakerDiarizationStatus(str, enum.Enum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


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
    enable_speaker_diarization: Mapped[bool] = mapped_column(default=False, nullable=False)
    speaker_diarization_status: Mapped[SpeakerDiarizationStatus] = mapped_column(
        Enum(
            SpeakerDiarizationStatus,
            values_callable=lambda enum_class: [item.value for item in enum_class],
        ),
        default=SpeakerDiarizationStatus.NOT_REQUESTED,
        nullable=False,
    )
    speaker_diarization_turns: Mapped[list | None] = mapped_column(JSON, nullable=True)
    speaker_diarization_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    speaker_diarization_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    speaker_diarization_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
    chunks = relationship(
        "TranscriptionChunk",
        back_populates="transcription_job",
        cascade="all, delete-orphan",
        order_by="TranscriptionChunk.chunk_index",
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


class TranscriptionChunk(Base):
    __tablename__ = "transcription_chunks"
    __table_args__ = (
        UniqueConstraint(
            "transcription_job_id",
            "chunk_index",
            name="uq_transcription_chunks_job_chunk_index",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transcription_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcription_jobs.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # ASR output for this chunk. This is kept immutable enough to audit LLM edits.
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_segments: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Per-chunk LLM refinement output.
    refinement_status: Mapped[ChunkRefinementStatus] = mapped_column(
        Enum(
            ChunkRefinementStatus,
            values_callable=lambda enum_class: [item.value for item in enum_class],
        ),
        default=ChunkRefinementStatus.PENDING,
        nullable=False,
    )
    refined_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )
    refinement_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    refinement_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    transcription_job = relationship("TranscriptionJob", back_populates="chunks")
    user = relationship("User", backref="transcription_chunks")
