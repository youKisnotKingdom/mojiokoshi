#!/usr/bin/env python3
"""Create initial admin user."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from getpass import getpass

from app.database import SessionLocal
from app.services import auth as auth_service


def main():
    print("=" * 50)
    print("Create Admin User")
    print("=" * 50)

    display_name = input("Display Name: ").strip()
    if not display_name:
        print("Error: Display name is required")
        sys.exit(1)

    password = getpass("Password: ")
    if len(password) < 4:
        print("Error: Password must be at least 4 characters")
        sys.exit(1)

    password_confirm = getpass("Confirm Password: ")
    if password != password_confirm:
        print("Error: Passwords do not match")
        sys.exit(1)

    db = SessionLocal()
    try:
        user = auth_service.create_admin_user(db, display_name, password)
        print()
        print("=" * 50)
        print("Admin user created successfully!")
        print("=" * 50)
        print(f"User ID: {user.user_id}")
        print(f"Display Name: {user.display_name}")
        print(f"Role: {user.role.value}")
        print("=" * 50)
        print("IMPORTANT: Save the User ID - it cannot be recovered!")
        print("=" * 50)
    except Exception as e:
        print(f"Error creating user: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
