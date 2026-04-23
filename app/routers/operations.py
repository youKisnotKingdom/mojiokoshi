from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin_user, verify_csrf_token
from app.models.user import User
from app.services import operations
from app.templating import templates

router = APIRouter(prefix="/admin/operations", tags=["operations"])


def _safe_next_url(next_url: str | None) -> str:
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/admin/operations"


@router.get("", response_class=HTMLResponse)
async def operations_dashboard(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin_user)],
):
    snapshot = operations.build_operations_snapshot(db)
    return templates.TemplateResponse(
        "admin/operations/dashboard.html",
        {
            "request": request,
            "title": "運用状況",
            "current_user": admin,
            "snapshot": snapshot,
        },
    )


@router.get("/api/snapshot")
async def operations_snapshot(
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin_user)],
):
    return operations.build_operations_snapshot(db)


@router.post("/transcriptions/{job_id}/requeue")
async def requeue_transcription(
    request: Request,
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin_user)],
):
    form = await request.form()
    csrf_token = form.get("csrf_token", "")
    next_url = _safe_next_url(form.get("next"))
    if not verify_csrf_token(csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRFトークンが無効です")

    try:
        job = operations.requeue_transcription_job(db, job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not job:
        raise HTTPException(status_code=404, detail="文字起こしジョブが見つかりません")

    return RedirectResponse(url=next_url, status_code=303)


@router.post("/summaries/{summary_id}/requeue")
async def requeue_summary(
    request: Request,
    summary_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin_user)],
):
    form = await request.form()
    csrf_token = form.get("csrf_token", "")
    next_url = _safe_next_url(form.get("next"))
    if not verify_csrf_token(csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRFトークンが無効です")

    try:
        summary = operations.requeue_summary_job(db, summary_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not summary:
        raise HTTPException(status_code=404, detail="要約ジョブが見つかりません")

    return RedirectResponse(url=next_url, status_code=303)
