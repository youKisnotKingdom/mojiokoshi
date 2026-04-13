"""add transcription_text to recording_chunk

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recording_chunks",
        sa.Column("transcription_text", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recording_chunks", "transcription_text")
