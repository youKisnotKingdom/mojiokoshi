"""
History router for viewing transcription jobs.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_user
from app.models import TranscriptionJob
from app.models.user import User
from app.templating import templates

router = APIRouter(prefix="/history", tags=["history"])

ITEMS_PER_PAGE = 20


@router.get("", response_class=HTMLResponse)
async def history_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    page: int = 1,
):
    """List all transcription jobs for the current user."""
    # Calculate pagination
    offset = (page - 1) * ITEMS_PER_PAGE

    # Get total count
    count_stmt = (
        select(func.count())
        .select_from(TranscriptionJob)
        .where(TranscriptionJob.user_id == current_user.id)
    )
    total_count = db.execute(count_stmt).scalar() or 0
    total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    # Get jobs with audio file
    stmt = (
        select(TranscriptionJob)
        .options(joinedload(TranscriptionJob.audio_file))
        .where(TranscriptionJob.user_id == current_user.id)
        .order_by(TranscriptionJob.created_at.desc())
        .offset(offset)
        .limit(ITEMS_PER_PAGE)
    )
    jobs = db.execute(stmt).unique().scalars().all()

    return templates.TemplateResponse(
        "history/index.html",
        {
            "request": request,
            "title": "履歴",
            "current_user": current_user,
            "jobs": jobs,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "offset": offset,
        },
    )
