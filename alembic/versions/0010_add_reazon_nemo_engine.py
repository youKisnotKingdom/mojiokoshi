"""add reazon nemo transcription engine

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-14

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE transcriptionengine ADD VALUE IF NOT EXISTS 'reazon_nemo_v2'")
    op.execute("ALTER TYPE transcriptionengine ADD VALUE IF NOT EXISTS 'REAZON_NEMO_V2'")


def downgrade() -> None:
    # PostgreSQL enum value removal is intentionally omitted.
    pass
