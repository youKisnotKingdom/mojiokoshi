"""add speaker diarization status

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

speakerdiarizationstatus = postgresql.ENUM(
    "not_requested",
    "pending",
    "processing",
    "completed",
    "failed",
    name="speakerdiarizationstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("transcription_jobs")}

    speakerdiarizationstatus.create(bind, checkfirst=True)

    if "speaker_diarization_status" not in columns:
        op.add_column(
            "transcription_jobs",
            sa.Column(
                "speaker_diarization_status",
                speakerdiarizationstatus,
                nullable=False,
                server_default="not_requested",
            ),
        )
        op.create_index(
            "ix_transcription_jobs_speaker_diarization_status",
            "transcription_jobs",
            ["speaker_diarization_status"],
            unique=False,
        )
        op.execute(
            """
            UPDATE transcription_jobs
            SET speaker_diarization_status = 'pending'
            WHERE enable_speaker_diarization = true
              AND status::text IN ('completed', 'COMPLETED')
              AND result_text IS NOT NULL
              AND speaker_diarization_status = 'not_requested'
            """
        )
        op.alter_column(
            "transcription_jobs",
            "speaker_diarization_status",
            server_default=None,
        )

    if "speaker_diarization_turns" not in columns:
        op.add_column(
            "transcription_jobs",
            sa.Column("speaker_diarization_turns", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        )
    if "speaker_diarization_error" not in columns:
        op.add_column("transcription_jobs", sa.Column("speaker_diarization_error", sa.Text(), nullable=True))
    if "speaker_diarization_started_at" not in columns:
        op.add_column(
            "transcription_jobs",
            sa.Column("speaker_diarization_started_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "speaker_diarization_completed_at" not in columns:
        op.add_column(
            "transcription_jobs",
            sa.Column("speaker_diarization_completed_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("transcription_jobs")}
    indexes = {index["name"] for index in inspector.get_indexes("transcription_jobs")}

    if "ix_transcription_jobs_speaker_diarization_status" in indexes:
        op.drop_index("ix_transcription_jobs_speaker_diarization_status", table_name="transcription_jobs")
    if "speaker_diarization_completed_at" in columns:
        op.drop_column("transcription_jobs", "speaker_diarization_completed_at")
    if "speaker_diarization_started_at" in columns:
        op.drop_column("transcription_jobs", "speaker_diarization_started_at")
    if "speaker_diarization_error" in columns:
        op.drop_column("transcription_jobs", "speaker_diarization_error")
    if "speaker_diarization_turns" in columns:
        op.drop_column("transcription_jobs", "speaker_diarization_turns")
    if "speaker_diarization_status" in columns:
        op.drop_column("transcription_jobs", "speaker_diarization_status")

    speakerdiarizationstatus.drop(bind, checkfirst=True)
