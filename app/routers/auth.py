from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    create_session_token,
    get_current_user,
    get_current_user_optional,
    limiter,
    verify_csrf_token,
)
from app.models.user import User
from app.schemas.user import LoginRequest, LoginResponse, UserResponse
from app.services import auth as auth_service
from app.templating import templates

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    user: Annotated[User | None, Depends(get_current_user_optional)],
):
    """Show login page."""
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "title": "ログイン"},
    )


@router.post("/login")
@limiter.limit("5/minute")
async def login(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user_id: Annotated[str, Form()],
    password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
):
    """Process login form."""
    if not verify_csrf_token(csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRFトークンが無効です",
        )

    user = auth_service.authenticate_user(db, user_id, password)

    if not user:
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "title": "ログイン",
                "error": "ユーザーIDまたはパスワードが正しくありません",
                "user_id": user_id,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    # Create session and redirect
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    session_token = create_session_token(user.id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )

    return response


@router.post("/logout")
async def logout():
    """Logout and clear session."""
    response = RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@router.get("/logout")
async def logout_get():
    """Logout via GET (for link convenience)."""
    return await logout()


# API endpoints for HTMX/JSON clients
@router.post("/api/login", response_model=LoginResponse)
async def api_login(
    db: Annotated[Session, Depends(get_db)],
    login_data: LoginRequest,
):
    """API login endpoint."""
    user = auth_service.authenticate_user(db, login_data.user_id, login_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ユーザーIDまたはパスワードが正しくありません",
        )

    return LoginResponse(
        message="ログインに成功しました",
        user=UserResponse.model_validate(user),
    )


@router.get("/api/me", response_model=UserResponse)
async def get_me(
    user: Annotated[User, Depends(get_current_user)],
):
    """Get current user info."""
    return UserResponse.model_validate(user)
