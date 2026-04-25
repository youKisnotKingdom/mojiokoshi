"""add speaker diarization flag to transcription jobs

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transcription_jobs",
        sa.Column(
            "enable_speaker_diarization",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.alter_column(
        "transcription_jobs",
        "enable_speaker_diarization",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("transcription_jobs", "enable_speaker_diarization")
