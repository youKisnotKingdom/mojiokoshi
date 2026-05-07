"""
History router for viewing transcription jobs.
"""
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import AudioFile, AudioSource, TranscriptionJob
from app.models.user import User
from app.services.transcription_access import can_manage_transcription_job, can_view_transcription_job
from app.templating import templates

router = APIRouter(prefix="/history", tags=["history"])
settings = get_settings()

ITEMS_PER_PAGE = 20
HISTORY_SCOPES = {"mine", "all"}


def _normalized_scope(scope: str | None) -> str:
    return scope if scope in HISTORY_SCOPES else "mine"


def _count_jobs_for_source(db: Session, current_user: User, source: AudioSource, scope: str) -> int:
    stmt = (
        select(func.count())
        .select_from(TranscriptionJob)
        .join(TranscriptionJob.audio_file)
        .where(AudioFile.source == source)
    )
    if scope == "mine":
        stmt = stmt.where(TranscriptionJob.user_id == current_user.id)
    return db.execute(stmt).scalar() or 0


def _with_history_filters(stmt, current_user: User, source: AudioSource, scope: str, query: str):
    stmt = stmt.join(TranscriptionJob.audio_file).join(TranscriptionJob.user)
    stmt = stmt.where(AudioFile.source == source)
    if scope == "mine":
        stmt = stmt.where(TranscriptionJob.user_id == current_user.id)
    if query:
        like_query = f"%{query}%"
        stmt = stmt.where(
            or_(
                AudioFile.original_filename.ilike(like_query),
                User.display_name.ilike(like_query),
                User.user_id.ilike(like_query),
                TranscriptionJob.result_text.ilike(like_query),
            )
        )
    return stmt


def _render_history_page(
    request: Request,
    db: Session,
    current_user: User,
    *,
    source: AudioSource,
    page: int,
    history_title: str,
    history_path: str,
    scope: str,
    query: str | None,
):
    page = max(1, page)
    offset = (page - 1) * ITEMS_PER_PAGE
    scope = _normalized_scope(scope)
    query = (query or "").strip()

    count_stmt = _with_history_filters(
        select(func.count()).select_from(TranscriptionJob),
        current_user,
        source,
        scope,
        query,
    )
    total_count = db.execute(count_stmt).scalar() or 0
    total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    stmt = _with_history_filters(
        select(TranscriptionJob).options(
            joinedload(TranscriptionJob.audio_file),
            joinedload(TranscriptionJob.user),
        ),
        current_user,
        source,
        scope,
        query,
    ).order_by(TranscriptionJob.created_at.desc())
    stmt = (
        stmt
        .offset(offset)
        .limit(ITEMS_PER_PAGE)
    )
    jobs = [
        job
        for job in db.execute(stmt).unique().scalars().all()
        if can_view_transcription_job(current_user, job)
    ]
    query_params = {"scope": scope}
    if query:
        query_params["q"] = query
    pagination_base = f"{history_path}?{urlencode(query_params)}&"
    current_params = dict(query_params)
    if page > 1:
        current_params["page"] = str(page)
    current_history_url = f"{history_path}?{urlencode(current_params)}"

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
            "history_scope": scope,
            "history_query": query,
            "pagination_base": pagination_base,
            "current_history_url": current_history_url,
            "active_history_source": source.value,
            "upload_count": _count_jobs_for_source(db, current_user, AudioSource.UPLOAD, scope),
            "recording_count": _count_jobs_for_source(db, current_user, AudioSource.RECORDING, scope),
            "enable_realtime_transcription": settings.enable_realtime_transcription,
            "can_manage_transcription_job": can_manage_transcription_job,
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
    scope: str = "mine",
    q: str | None = None,
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
        scope=scope,
        query=q,
    )


@router.get("/recordings", response_class=HTMLResponse)
async def recording_history_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    page: int = 1,
    scope: str = "mine",
    q: str | None = None,
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
        scope=scope,
        query=q,
    )
