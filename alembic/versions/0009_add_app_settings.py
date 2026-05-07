"""add app settings

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-01

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("app_settings"):
        op.create_table(
            "app_settings",
            sa.Column("key", sa.String(length=100), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("updated_by_id", sa.Integer(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("key"),
        )


def downgrade() -> None:
    op.drop_table("app_settings")
