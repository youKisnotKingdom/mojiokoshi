from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.services import auth as auth_service

settings = get_settings()

# Session serializer
serializer = URLSafeTimedSerializer(settings.secret_key)

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
            detail="Not authenticated",
        )
    return user


def get_current_admin_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get the current user, raising 403 if not an admin."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
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
