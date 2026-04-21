"""
History router for viewing transcription jobs.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import AudioFile, AudioSource, TranscriptionJob
from app.models.user import User
from app.templating import templates

router = APIRouter(prefix="/history", tags=["history"])
settings = get_settings()

ITEMS_PER_PAGE = 20


def _count_jobs_for_source(db: Session, user_id: int, source: AudioSource) -> int:
    stmt = (
        select(func.count())
        .select_from(TranscriptionJob)
        .join(TranscriptionJob.audio_file)
        .where(TranscriptionJob.user_id == user_id)
        .where(AudioFile.source == source)
    )
    return db.execute(stmt).scalar() or 0


def _render_history_page(
    request: Request,
    db: Session,
    current_user: User,
    *,
    source: AudioSource,
    page: int,
    history_title: str,
    history_path: str,
):
    page = max(1, page)
    offset = (page - 1) * ITEMS_PER_PAGE

    count_stmt = (
        select(func.count())
        .select_from(TranscriptionJob)
        .join(TranscriptionJob.audio_file)
        .where(TranscriptionJob.user_id == current_user.id)
        .where(AudioFile.source == source)
    )
    total_count = db.execute(count_stmt).scalar() or 0
    total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    stmt = (
        select(TranscriptionJob)
        .options(joinedload(TranscriptionJob.audio_file))
        .join(TranscriptionJob.audio_file)
        .where(TranscriptionJob.user_id == current_user.id)
        .where(AudioFile.source == source)
        .order_by(TranscriptionJob.created_at.desc())
        .offset(offset)
        .limit(ITEMS_PER_PAGE)
    )
    jobs = db.execute(stmt).unique().scalars().all()

    return templates.TemplateResponse(
        "history/index.html",
        {
            "request": request,
            "title": history_title,
            "history_title": history_title,
            "current_user": current_user,
            "jobs": jobs,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "offset": offset,
            "history_path": history_path,
            "active_history_source": source.value,
            "upload_count": _count_jobs_for_source(db, current_user.id, AudioSource.UPLOAD),
            "recording_count": _count_jobs_for_source(db, current_user.id, AudioSource.RECORDING),
            "enable_realtime_transcription": settings.enable_realtime_transcription,
        },
    )


@router.get("", response_class=HTMLResponse)
async def history_root():
    """Redirect to the primary upload history view."""
    return RedirectResponse(url="/history/uploads", status_code=303)


@router.get("/uploads", response_class=HTMLResponse)
async def upload_history_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    page: int = 1,
):
    """List uploaded-file transcription jobs for the current user."""
    return _render_history_page(
        request,
        db,
        current_user,
        source=AudioSource.UPLOAD,
        page=page,
        history_title="アップロード履歴",
        history_path="/history/uploads",
    )


@router.get("/recordings", response_class=HTMLResponse)
async def recording_history_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    page: int = 1,
):
    """List browser-recording transcription jobs for the current user."""
    return _render_history_page(
        request,
        db,
        current_user,
        source=AudioSource.RECORDING,
        page=page,
        history_title="録音履歴",
        history_path="/history/recordings",
    )
