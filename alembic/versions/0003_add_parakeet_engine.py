"""add parakeet transcription engine

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-22

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE transcriptionengine ADD VALUE IF NOT EXISTS 'parakeet_ja'")
    op.execute("ALTER TYPE transcriptionengine ADD VALUE IF NOT EXISTS 'PARAKEET_JA'")


def downgrade() -> None:
    # PostgreSQL enum value removal is intentionally omitted.
    pass
