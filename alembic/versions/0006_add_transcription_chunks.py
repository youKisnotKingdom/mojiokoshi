"""add transcription chunks

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

chunkrefinementstatus = postgresql.ENUM(
    "pending",
    "processing",
    "completed",
    "failed",
    "skipped",
    name="chunkrefinementstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    chunkrefinementstatus.create(bind, checkfirst=True)

    if not inspector.has_table("transcription_chunks"):
        op.create_table(
            "transcription_chunks",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("transcription_job_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("start_seconds", sa.Float(), nullable=False),
            sa.Column("end_seconds", sa.Float(), nullable=False),
            sa.Column("raw_text", sa.Text(), nullable=False),
            sa.Column("raw_segments", postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column(
                "refinement_status",
                chunkrefinementstatus,
                nullable=False,
                server_default="pending",
            ),
            sa.Column("refined_text", sa.Text(), nullable=True),
            sa.Column("model_name", sa.String(length=100), nullable=True),
            sa.Column("token_usage", postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("refinement_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("refinement_completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["transcription_job_id"], ["transcription_jobs.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "transcription_job_id",
                "chunk_index",
                name="uq_transcription_chunks_job_chunk_index",
            ),
        )
        op.create_index(
            "ix_transcription_chunks_refinement_status",
            "transcription_chunks",
            ["refinement_status"],
            unique=False,
        )
        op.create_index(
            "ix_transcription_chunks_job_index",
            "transcription_chunks",
            ["transcription_job_id", "chunk_index"],
            unique=False,
        )

    op.alter_column("transcription_chunks", "refinement_status", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_transcription_chunks_job_index", table_name="transcription_chunks")
    op.drop_index("ix_transcription_chunks_refinement_status", table_name="transcription_chunks")
    op.drop_table("transcription_chunks")
    chunkrefinementstatus.drop(op.get_bind(), checkfirst=True)
