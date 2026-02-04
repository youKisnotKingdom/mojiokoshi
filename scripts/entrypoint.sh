#!/bin/bash
set -e

# Wait for database to be ready
echo "Waiting for database..."
while ! python -c "from app.database import engine; engine.connect()" 2>/dev/null; do
    sleep 1
done
echo "Database is ready."

# Initialize database tables
echo "Initializing database..."
python scripts/init_db.py

# Create admin user if specified
if [ -n "$ADMIN_USER_ID" ] && [ -n "$ADMIN_PASSWORD" ]; then
    echo "Creating admin user..."
    python scripts/init_db.py --create-admin --admin-id "$ADMIN_USER_ID" --admin-password "$ADMIN_PASSWORD"
fi

# Execute the main command
exec "$@"
