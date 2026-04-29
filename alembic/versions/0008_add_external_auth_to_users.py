"""add external auth fields to users

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-26

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    indexes = {index["name"] for index in inspector.get_indexes("users")}

    if "external_auth_provider" not in columns:
        op.add_column(
            "users",
            sa.Column("external_auth_provider", sa.String(length=50), nullable=True),
        )
    if "external_auth_id" not in columns:
        op.add_column(
            "users",
            sa.Column("external_auth_id", sa.String(length=255), nullable=True),
        )
    if "ix_users_external_auth" not in indexes:
        op.create_index(
            "ix_users_external_auth",
            "users",
            ["external_auth_provider", "external_auth_id"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    indexes = {index["name"] for index in inspector.get_indexes("users")}

    if "ix_users_external_auth" in indexes:
        op.drop_index("ix_users_external_auth", table_name="users")
    if "external_auth_id" in columns:
        op.drop_column("users", "external_auth_id")
    if "external_auth_provider" in columns:
        op.drop_column("users", "external_auth_provider")
