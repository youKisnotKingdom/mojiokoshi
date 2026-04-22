"""fix parakeet transcription engine enum label

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-22

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE transcriptionengine ADD VALUE IF NOT EXISTS 'PARAKEET_JA'")


def downgrade() -> None:
    # PostgreSQL enum value removal is intentionally omitted.
    pass
