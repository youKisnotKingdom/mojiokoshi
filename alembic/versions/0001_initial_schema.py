"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False にして op.create_table 内で再作成が走らないようにする
userrole = postgresql.ENUM("admin", "user", name="userrole", create_type=False)
audiosource = postgresql.ENUM("upload", "recording", name="audiosource", create_type=False)
recordingstatus = postgresql.ENUM(
    "recording", "paused", "completed", "failed", name="recordingstatus", create_type=False
)
transcriptionstatus = postgresql.ENUM(
    "pending", "processing", "completed", "failed",
    name="transcriptionstatus", create_type=False,
)
transcriptionengine = postgresql.ENUM(
    "whisper", "faster_whisper", "qwen_asr",
    name="transcriptionengine", create_type=False,
)
summarystatus = postgresql.ENUM(
    "pending", "processing", "completed", "failed",
    name="summarystatus", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- Enum types（存在しない場合のみ作成）---
    for enum in [userrole, audiosource, recordingstatus,
                 transcriptionstatus, transcriptionengine, summarystatus]:
        enum.create(bind, checkfirst=True)

    # --- users ---
    if not inspector.has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.String(6), nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("display_name", sa.String(100), nullable=False),
            sa.Column("role", userrole, nullable=False, server_default="user"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.text("now()"), nullable=False,
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True),
                server_default=sa.text("now()"), nullable=False,
            ),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_users_user_id", "users", ["user_id"], unique=True)

    # --- prompt_templates ---
    if not inspector.has_table("prompt_templates"):
        op.create_table(
            "prompt_templates",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("system_prompt", sa.Text(), nullable=False),
            sa.Column("user_prompt_template", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.text("now()"), nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    # --- audio_files ---
    if not inspector.has_table("audio_files"):
        op.create_table(
            "audio_files",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("source", audiosource, nullable=False, server_default="upload"),
            sa.Column("original_filename", sa.String(255), nullable=False),
            sa.Column("stored_filename", sa.String(255), nullable=False),
            sa.Column("file_path", sa.String(500), nullable=False),
            sa.Column("file_size", sa.BigInteger(), nullable=False),
            sa.Column("mime_type", sa.String(100), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.text("now()"), nullable=False,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    # --- recording_sessions ---
    if not inspector.has_table("recording_sessions"):
        op.create_table(
            "recording_sessions",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("status", recordingstatus, nullable=False, server_default="recording"),
            sa.Column("total_duration_seconds", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("audio_file_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.text("now()"), nullable=False,
            ),
            sa.Column(
                "started_at", sa.DateTime(timezone=True),
                server_default=sa.text("now()"), nullable=False,
            ),
            sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["audio_file_id"], ["audio_files.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    # --- recording_chunks ---
    if not inspector.has_table("recording_chunks"):
        op.create_table(
            "recording_chunks",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("file_path", sa.String(500), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False),
            sa.Column("duration_seconds", sa.Float(), nullable=False),
            sa.Column(
                "received_at", sa.DateTime(timezone=True),
                server_default=sa.text("now()"), nullable=False,
            ),
            sa.ForeignKeyConstraint(["session_id"], ["recording_sessions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    # --- transcription_jobs ---
    if not inspector.has_table("transcription_jobs"):
        op.create_table(
            "transcription_jobs",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("audio_file_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("status", transcriptionstatus, nullable=False, server_default="pending"),
            sa.Column("engine", transcriptionengine, nullable=False, server_default="faster_whisper"),
            sa.Column("model_size", sa.String(50), nullable=False, server_default="large"),
            sa.Column("language", sa.String(10), nullable=True),
            sa.Column("result_text", sa.Text(), nullable=True),
            sa.Column("result_segments", postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column("progress_percent", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.text("now()"), nullable=False,
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["audio_file_id"], ["audio_files.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    # --- summaries ---
    if not inspector.has_table("summaries"):
        op.create_table(
            "summaries",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("transcription_job_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("status", summarystatus, nullable=False, server_default="pending"),
            sa.Column("prompt_template_id", sa.Integer(), nullable=True),
            sa.Column("custom_prompt", sa.Text(), nullable=True),
            sa.Column("result_text", sa.Text(), nullable=True),
            sa.Column("model_name", sa.String(100), nullable=True),
            sa.Column("token_usage", postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.text("now()"), nullable=False,
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["prompt_template_id"], ["prompt_templates.id"]),
            sa.ForeignKeyConstraint(["transcription_job_id"], ["transcription_jobs.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    op.drop_table("summaries")
    op.drop_table("transcription_jobs")
    op.drop_table("recording_chunks")
    op.drop_table("recording_sessions")
    op.drop_table("audio_files")
    op.drop_table("prompt_templates")
    op.drop_table("users")

    for enum in [summarystatus, transcriptionengine, transcriptionstatus,
                 recordingstatus, audiosource, userrole]:
        enum.drop(op.get_bind(), checkfirst=True)
