"""add cohere transcribe engine

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-14

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE transcriptionengine ADD VALUE IF NOT EXISTS 'cohere_transcribe'")
    op.execute("ALTER TYPE transcriptionengine ADD VALUE IF NOT EXISTS 'COHERE_TRANSCRIBE'")


def downgrade() -> None:
    # PostgreSQL enum value removal is intentionally omitted.
    pass
