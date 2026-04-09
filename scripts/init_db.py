#!/usr/bin/env python3
"""
Database initialization script.

NOTE: Schema creation is now managed by Alembic migrations.
Run `alembic upgrade head` to create or update tables.

This script is kept only for legacy compatibility and seeding initial data.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

print(
    "NOTICE: Table creation is now handled by Alembic.\n"
    "Run: alembic upgrade head\n"
    "To create an admin user, use: python scripts/create_admin.py"
)
