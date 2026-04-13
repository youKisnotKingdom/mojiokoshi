#!/bin/bash
set -e

# Validate required environment variables
if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "change-me-in-production" ]; then
    echo "ERROR: SECRET_KEY environment variable must be set to a secure random value."
    echo "  Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    exit 1
fi

# Wait for database to be ready
echo "Waiting for database..."
while ! python -c "
import os, psycopg2
psycopg2.connect(os.environ['DATABASE_URL'])
" 2>/dev/null; do
    sleep 1
done
echo "Database is ready."

# Apply database migrations
echo "Running database migrations..."
alembic upgrade head
echo "Migrations applied."

# Create admin user if specified (skip if already exists)
if [ -n "$ADMIN_USER_ID" ] && [ -n "$ADMIN_PASSWORD" ]; then
    echo "Creating admin user (skip if exists)..."
    python scripts/create_admin.py --admin-id "$ADMIN_USER_ID" --admin-password "$ADMIN_PASSWORD"
fi

# Execute the main command
exec "$@"
