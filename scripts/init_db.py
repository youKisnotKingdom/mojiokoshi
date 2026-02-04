#!/usr/bin/env python3
"""
Database initialization script.
Creates all tables and optionally creates an admin user.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base, engine, SessionLocal
from app.models import *  # Import all models to register them
from app.services.auth import create_user, get_user_by_id


def init_db():
    """Create all database tables."""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully.")


def create_admin_user(user_id: str, password: str):
    """Create an admin user."""
    from app.models.user import UserRole

    db = SessionLocal()
    try:
        # Check if user already exists
        existing = get_user_by_id(db, int(user_id))
        if existing:
            print(f"User {user_id} already exists.")
            return

        user = create_user(
            db,
            user_id=user_id,
            password=password,
            display_name="Administrator",
            role=UserRole.ADMIN,
        )
        print(f"Admin user created: {user.user_id}")

    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Initialize database")
    parser.add_argument("--create-admin", action="store_true", help="Create admin user")
    parser.add_argument("--admin-id", type=str, default="000001", help="Admin user ID")
    parser.add_argument("--admin-password", type=str, help="Admin password")

    args = parser.parse_args()

    # Initialize database
    init_db()

    # Create admin if requested
    if args.create_admin:
        if not args.admin_password:
            import getpass
            args.admin_password = getpass.getpass("Enter admin password: ")

        create_admin_user(args.admin_id, args.admin_password)
