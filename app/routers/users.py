from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin_user, get_current_user, verify_csrf_token
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserResponse, UserUpdate
from app.services import auth as auth_service
from app.templating import templates

router = APIRouter(prefix="/admin/users", tags=["users"])


@router.get("", response_class=HTMLResponse)
async def users_list_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin_user)],
):
    """Show users management page."""
    users = auth_service.get_users(db, include_inactive=True)
    return templates.TemplateResponse(
        "admin/users/list.html",
        {
            "request": request,
            "title": "ユーザー管理",
            "users": users,
            "current_user": admin,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_user_page(
    request: Request,
    admin: Annotated[User, Depends(get_current_admin_user)],
):
    """Show new user form."""
    return templates.TemplateResponse(
        "admin/users/form.html",
        {
            "request": request,
            "title": "新規ユーザー",
            "user": None,
            "roles": UserRole,
            "current_user": admin,
        },
    )


@router.post("/new")
async def create_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin_user)],
    display_name: Annotated[str, Form()],
    password: Annotated[str, Form()],
    role: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
):
    """Create a new user."""
    if not verify_csrf_token(csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRFトークンが無効です")
    try:
        user_role = UserRole(role)
    except ValueError:
        user_role = UserRole.USER

    user_data = UserCreate(
        display_name=display_name,
        password=password,
        role=user_role,
    )

    user = auth_service.create_user(db, user_data)

    return templates.TemplateResponse(
        "admin/users/created.html",
        {
            "request": request,
            "title": "ユーザー作成完了",
            "user": user,
            "current_user": admin,
        },
    )


@router.get("/{user_id}", response_class=HTMLResponse)
async def edit_user_page(
    request: Request,
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin_user)],
):
    """Show edit user form."""
    user = auth_service.get_user_by_user_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

    return templates.TemplateResponse(
        "admin/users/form.html",
        {
            "request": request,
            "title": f"ユーザー編集: {user.display_name}",
            "user": user,
            "roles": UserRole,
            "current_user": admin,
        },
    )


@router.post("/{user_id}")
async def update_user(
    request: Request,
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin_user)],
    display_name: Annotated[str, Form()],
    role: Annotated[str, Form()],
    is_active: Annotated[bool, Form()] = False,
    csrf_token: Annotated[str, Form()] = "",
):
    """Update a user."""
    if not verify_csrf_token(csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRFトークンが無効です")

    user = auth_service.get_user_by_user_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

    try:
        user_role = UserRole(role)
    except ValueError:
        user_role = user.role

    # Prevent admin from deactivating themselves
    if user.id == admin.id and not is_active:
        return templates.TemplateResponse(
            "admin/users/form.html",
            {
                "request": request,
                "title": f"ユーザー編集: {user.display_name}",
                "user": user,
                "roles": UserRole,
                "current_user": admin,
                "error": "自分自身のアカウントを無効化することはできません",
            },
        )

    auth_service.update_user(
        db,
        user,
        display_name=display_name,
        role=user_role,
        is_active=is_active,
    )

    return templates.TemplateResponse(
        "admin/users/form.html",
        {
            "request": request,
            "title": f"ユーザー編集: {user.display_name}",
            "user": user,
            "roles": UserRole,
            "current_user": admin,
            "success": "ユーザー情報を更新しました",
        },
    )


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    request: Request,
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin_user)],
    new_password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
):
    """Reset a user's password."""
    if not verify_csrf_token(csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRFトークンが無効です")

    user = auth_service.get_user_by_user_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

    auth_service.update_user_password(db, user, new_password)

    return templates.TemplateResponse(
        "admin/users/form.html",
        {
            "request": request,
            "title": f"ユーザー編集: {user.display_name}",
            "user": user,
            "roles": UserRole,
            "current_user": admin,
            "success": "パスワードをリセットしました",
        },
    )


# API endpoints
@router.get("/api/", response_model=list[UserResponse])
async def api_get_users(
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin_user)],
    include_inactive: bool = False,
):
    """Get all users (API)."""
    users = auth_service.get_users(db, include_inactive=include_inactive)
    return [UserResponse.model_validate(u) for u in users]


@router.post("/api/", response_model=UserResponse)
async def api_create_user(
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin_user)],
    user_data: UserCreate,
):
    """Create a new user (API)."""
    user = auth_service.create_user(db, user_data)
    return UserResponse.model_validate(user)
