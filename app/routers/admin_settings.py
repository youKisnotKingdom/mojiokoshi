from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin_user, verify_csrf_token
from app.models.user import User
from app.services import runtime_settings
from app.templating import templates

router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])


@router.get("", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin_user)],
    saved: bool = False,
):
    runtime_settings.apply_runtime_settings(db)
    return templates.TemplateResponse(
        "admin/settings/index.html",
        {
            "request": request,
            "title": "管理設定",
            "current_user": admin,
            "setting_groups": runtime_settings.build_settings_view(db),
            "saved": saved,
            "errors": {},
        },
    )


@router.post("", response_class=HTMLResponse)
async def update_settings(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin_user)],
):
    form = await request.form()
    csrf_token = form.get("csrf_token", "")
    if not verify_csrf_token(csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRFトークンが無効です")

    submitted_values, values, reset_keys, errors = runtime_settings.parse_settings_form(form)
    if errors:
        return templates.TemplateResponse(
            "admin/settings/index.html",
            {
                "request": request,
                "title": "管理設定",
                "current_user": admin,
                "setting_groups": runtime_settings.build_settings_view(db, submitted_values, errors),
                "saved": False,
                "errors": errors,
            },
            status_code=400,
        )

    runtime_settings.save_runtime_settings(
        db,
        values,
        reset_keys,
        updated_by_id=admin.id,
    )
    return RedirectResponse(url="/admin/settings?saved=1", status_code=303)
