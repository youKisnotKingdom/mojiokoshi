"""
Pytest configuration and shared fixtures.

Uses SQLite in-memory DB for tests by default.
Set TEST_DATABASE_URL to use PostgreSQL instead.
"""
import os
import uuid

# Set required env vars before importing any app module
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used-in-production-32chars")
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL", "sqlite:///./test_mojiokoshi.db"),
)
os.environ["SKIP_STARTUP_CHECKS"] = "1"  # Skip LLM reachability check in tests

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "sqlite:///./test_mojiokoshi.db")

engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False} if "sqlite" in TEST_DB_URL else {},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Create all tables once per test session, drop at end."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    """Transactional session that rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def isolate_rate_limiter():
    """Reset rate limiter storage after each test so limits don't bleed across tests."""
    yield
    try:
        from app.dependencies import limiter
        limiter._storage.reset()
    except Exception:
        pass


@pytest.fixture
def client(db):
    """FastAPI TestClient with test database injected."""
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_user(db):
    """Create and return an admin user."""
    from app.models.user import User, UserRole
    from app.services.auth import get_password_hash

    user = User(
        user_id="000001",
        password_hash=get_password_hash("AdminPass1"),
        display_name="Test Admin",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def regular_user(db):
    """Create and return a regular user."""
    from app.models.user import User, UserRole
    from app.services.auth import get_password_hash

    user = User(
        user_id="000002",
        password_hash=get_password_hash("UserPass1"),
        display_name="Test User",
        role=UserRole.USER,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _get_csrf_token(client):
    """Extract CSRF token from the login page."""
    import re
    response = client.get("/auth/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    return match.group(1) if match else ""


@pytest.fixture
def admin_client(client, admin_user):
    """TestClient logged in as admin."""
    csrf = _get_csrf_token(client)
    client.post(
        "/auth/login",
        data={"user_id": "000001", "password": "AdminPass1", "csrf_token": csrf},
        follow_redirects=True,
    )
    return client


@pytest.fixture
def user_client(client, regular_user):
    """TestClient logged in as a regular user."""
    csrf = _get_csrf_token(client)
    client.post(
        "/auth/login",
        data={"user_id": "000002", "password": "UserPass1", "csrf_token": csrf},
        follow_redirects=True,
    )
    return client
