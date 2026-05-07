import enum
import uuid
from datetime import datetime, timezone
from math import ceil

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.time_utils import utc_now


class AudioSource(str, enum.Enum):
    UPLOAD = "upload"
    RECORDING = "recording"


class AudioFile(Base):
    __tablename__ = "audio_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    source: Mapped[AudioSource] = mapped_column(
        Enum(AudioSource), default=AudioSource.UPLOAD, nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user = relationship("User", backref="audio_files")
    transcription_jobs = relationship(
        "TranscriptionJob", back_populates="audio_file", cascade="all, delete-orphan"
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def retention_days_remaining(self) -> int | None:
        """Whole days remaining before the physical audio file expires."""
        if self.deleted_at is not None or self.expires_at is None:
            return None
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        remaining_seconds = (expires_at - utc_now()).total_seconds()
        if remaining_seconds <= 0:
            return 0
        return max(1, ceil(remaining_seconds / 86400))

    @property
    def duration_display(self) -> str:
        if self.duration_seconds is None:
            return "Unknown"
        minutes = int(self.duration_seconds // 60)
        seconds = int(self.duration_seconds % 60)
        return f"{minutes:02d}:{seconds:02d}"
