import secrets
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.services import auth as auth_service

settings = get_settings()

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Session serializer
serializer = URLSafeTimedSerializer(settings.secret_key)

# CSRF serializer
_csrf_serializer = URLSafeTimedSerializer(settings.secret_key, salt="csrf-token")
CSRF_TOKEN_MAX_AGE = 60 * 60  # 1 hour


def generate_csrf_token() -> str:
    """Generate a signed, time-limited CSRF token."""
    return _csrf_serializer.dumps(secrets.token_hex(16))


def verify_csrf_token(token: str) -> bool:
    """Verify that a CSRF token is valid and not expired."""
    if not token:
        return False
    try:
        _csrf_serializer.loads(token, max_age=CSRF_TOKEN_MAX_AGE)
        return True
    except (SignatureExpired, BadSignature, Exception):
        return False

SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def create_session_token(user_id: int) -> str:
    """Create a signed session token."""
    return serializer.dumps({"user_id": user_id})


def verify_session_token(token: str) -> dict | None:
    """Verify and decode a session token."""
    try:
        return serializer.loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None


def get_current_user_optional(
    db: Annotated[Session, Depends(get_db)],
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User | None:
    """Get the current user from session cookie, or None if not logged in."""
    if not session:
        return None

    data = verify_session_token(session)
    if not data:
        return None

    user = auth_service.get_user_by_id(db, data["user_id"])
    if not user or not user.is_active:
        return None

    return user


def get_current_user(
    user: Annotated[User | None, Depends(get_current_user_optional)],
) -> User:
    """Get the current user, raising 401 if not logged in."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証されていません",
        )
    return user


def get_current_admin_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get the current user, raising 403 if not an admin."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理者権限が必要です",
        )
    return user


def get_user_from_session_cookie(session_cookie: str, db: Session) -> User | None:
    """Get user from session cookie value (for WebSocket authentication)."""
    if not session_cookie:
        return None

    data = verify_session_token(session_cookie)
    if not data:
        return None

    user = auth_service.get_user_by_id(db, data["user_id"])
    if not user or not user.is_active:
        return None

    return user
