import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user, limiter, verify_csrf_token
from app.models import AudioFile, AudioSource, Summary, TranscriptionEngine, TranscriptionJob, TranscriptionStatus
from app.models.user import User
from app.schemas.transcription import TranscriptionJobResponse
from app.services import storage
from app.services.speaker_diarization import build_speaker_blocks
from app.templating import templates
from app.time_utils import utc_now

settings = get_settings()
router = APIRouter(prefix="/transcription", tags=["transcription"])


def _max_upload_size_mb() -> int:
    mib = 1024 * 1024
    return max(1, (settings.max_upload_size + mib - 1) // mib)


def _upload_page_context(
    request: Request,
    current_user: User,
    *,
    error: str | None = None,
    speaker_diarization_requested: bool = False,
) -> dict[str, object]:
    return {
        "request": request,
        "title": "音声アップロード",
        "current_user": current_user,
        "engines": TranscriptionEngine,
        "error": error,
        "max_upload_size_mb": _max_upload_size_mb(),
        "default_engine": settings.default_transcription_engine,
        "speaker_diarization_enabled": settings.enable_speaker_diarization,
        "speaker_diarization_requested": speaker_diarization_requested,
    }


def _is_ajax_upload(request: Request) -> bool:
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _is_safe_internal_url(next_url: str | None) -> bool:
    return bool(next_url) and next_url.startswith("/") and not next_url.startswith("//")


def _history_url_for_source(source: AudioSource | None) -> str:
    if source == AudioSource.RECORDING:
        return "/history/recordings"
    return "/history/uploads"


def _upload_error_response(
    request: Request,
    current_user: User,
    error: str,
    *,
    status_code: int,
    speaker_diarization_requested: bool = False,
):
    if _is_ajax_upload(request):
        return JSONResponse(
            {
                "ok": False,
                "error": error,
            },
            status_code=status_code,
        )
    return templates.TemplateResponse(
        "transcription/upload.html",
        _upload_page_context(
            request,
            current_user,
            error=error,
            speaker_diarization_requested=speaker_diarization_requested,
        ),
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
async def transcription_page(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Main transcription page with options."""
    return templates.TemplateResponse(
        "transcription/index.html",
        {
            "request": request,
            "title": "文字起こし",
            "current_user": current_user,
            "enable_realtime_transcription": settings.enable_realtime_transcription,
        },
    )


@router.get("/upload", response_class=HTMLResponse)
async def upload_page(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """File upload page."""
    return templates.TemplateResponse(
        "transcription/upload.html",
        _upload_page_context(request, current_user),
    )


@router.post("/upload")
@limiter.limit("10/minute")
async def upload_file(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    file: Annotated[UploadFile, File()],
    engine: Annotated[str, Form()] = settings.default_transcription_engine,
    model_size: Annotated[str, Form()] = "medium",
    language: Annotated[str | None, Form()] = None,
    enable_speaker_diarization: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str, Form()] = "",
):
    """Handle file upload and create transcription job."""
    diarization_requested = settings.enable_speaker_diarization and bool(enable_speaker_diarization)

    if not verify_csrf_token(csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRFトークンが無効です",
        )
    # Validate file
    if not file.filename:
        return _upload_error_response(
            request,
            current_user,
            "ファイルが選択されていません",
            status_code=400,
            speaker_diarization_requested=diarization_requested,
        )

    # Check MIME type
    if not storage.validate_audio_mime_type(file.content_type):
        return _upload_error_response(
            request,
            current_user,
            f"無効なファイル形式です: {file.content_type}。音声ファイルをアップロードしてください。",
            status_code=400,
            speaker_diarization_requested=diarization_requested,
        )

    # Stream the upload to disk to keep memory usage bounded.
    try:
        stored_filename, file_path, file_size = await storage.save_upload_stream(
            file,
            file.filename,
            max_size=settings.max_upload_size,
            mime_type=file.content_type,
        )
    except ValueError:
        return _upload_error_response(
            request,
            current_user,
            f"ファイルが大きすぎます。最大サイズは{_max_upload_size_mb()}MBです。",
            status_code=400,
            speaker_diarization_requested=diarization_requested,
        )
    finally:
        await file.close()

    # Calculate expiration date
    expires_at = utc_now() + timedelta(days=settings.audio_retention_days)

    # Create audio file record
    audio_file = AudioFile(
        user_id=current_user.id,
        source=AudioSource.UPLOAD,
        original_filename=file.filename,
        stored_filename=stored_filename,
        file_path=file_path,
        file_size=file_size,
        mime_type=file.content_type,
        expires_at=expires_at,
    )
    db.add(audio_file)
    db.flush()

    # Create transcription job
    try:
        transcription_engine = TranscriptionEngine(engine)
    except ValueError:
        transcription_engine = TranscriptionEngine(settings.default_transcription_engine)

    effective_model_size = model_size
    if transcription_engine == TranscriptionEngine.PARAKEET_JA:
        effective_model_size = "parakeet-tdt_ctc-0.6b-ja"

    job = TranscriptionJob(
        audio_file_id=audio_file.id,
        user_id=current_user.id,
        engine=transcription_engine,
        model_size=effective_model_size,
        language=language if language else None,
        enable_speaker_diarization=diarization_requested,
    )
    db.add(job)
    db.commit()

    # Redirect to job status page
    redirect_url = f"/transcription/job/{job.id}"
    if _is_ajax_upload(request):
        return JSONResponse(
            {
                "ok": True,
                "redirect_url": redirect_url,
                "job_id": str(job.id),
            },
            status_code=201,
        )

    from fastapi.responses import RedirectResponse
    return RedirectResponse(
        url=redirect_url,
        status_code=303,
    )


@router.get("/record", response_class=HTMLResponse)
async def record_page(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Recording page."""
    if not settings.enable_realtime_transcription:
        raise HTTPException(status_code=404, detail="リアルタイム録音は無効です")

    return templates.TemplateResponse(
        "transcription/record.html",
        {
            "request": request,
            "title": "音声録音",
            "current_user": current_user,
        },
    )


@router.get("/job/{job_id}", response_class=HTMLResponse)
async def job_detail_page(
    request: Request,
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Job detail/progress page."""
    stmt = (
        select(TranscriptionJob)
        .where(TranscriptionJob.id == job_id)
        .where(TranscriptionJob.user_id == current_user.id)
    )
    job = db.execute(stmt).scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")

    # Get summaries for this job
    summary_stmt = (
        select(Summary)
        .where(Summary.transcription_job_id == job_id)
        .order_by(Summary.created_at.desc())
    )
    summaries = db.execute(summary_stmt).scalars().all()

    history_url = _history_url_for_source(job.audio_file.source if job.audio_file else None)

    return templates.TemplateResponse(
        "transcription/job_detail.html",
        {
            "request": request,
            "title": "文字起こしジョブ",
            "current_user": current_user,
            "job": job,
            "summaries": summaries,
            "history_url": history_url,
            "speaker_blocks": build_speaker_blocks(job.result_segments if isinstance(job.result_segments, list) else None),
            "speaker_diarization_requested": job.enable_speaker_diarization,
            "speaker_diarization_enabled": settings.enable_speaker_diarization,
        },
    )


@router.get("/job/{job_id}/progress", response_class=HTMLResponse)
async def job_progress_partial(
    request: Request,
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """HTMX partial for job progress."""
    stmt = (
        select(TranscriptionJob)
        .where(TranscriptionJob.id == job_id)
        .where(TranscriptionJob.user_id == current_user.id)
    )
    job = db.execute(stmt).scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")

    return templates.TemplateResponse(
        "transcription/partials/job_progress.html",
        {
            "request": request,
            "job": job,
        },
    )


@router.post("/job/{job_id}/delete")
async def delete_job(
    request: Request,
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    csrf_token: Annotated[str, Form()] = "",
    next_url: Annotated[str | None, Form()] = None,
):
    """Delete a transcription job and its associated audio file."""
    from fastapi.responses import RedirectResponse

    if not verify_csrf_token(csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRFトークンが無効です")

    stmt = (
        select(TranscriptionJob)
        .where(TranscriptionJob.id == job_id)
        .where(TranscriptionJob.user_id == current_user.id)
    )
    job = db.execute(stmt).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")

    redirect_url = next_url if _is_safe_internal_url(next_url) else _history_url_for_source(job.audio_file.source if job.audio_file else None)

    # Delete associated audio file (cascades to job and summaries)
    if job.audio_file:
        audio_file = job.audio_file
        # Try to remove the actual file
        import os
        try:
            if os.path.exists(audio_file.file_path):
                os.remove(audio_file.file_path)
        except OSError:
            pass
        db.delete(audio_file)
    else:
        db.delete(job)

    db.commit()
    return RedirectResponse(url=redirect_url, status_code=303)


# API endpoints
@router.get("/api/jobs", response_model=list[TranscriptionJobResponse])
async def get_jobs(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = 50,
    offset: int = 0,
):
    """Get user's transcription jobs."""
    stmt = (
        select(TranscriptionJob)
        .where(TranscriptionJob.user_id == current_user.id)
        .order_by(TranscriptionJob.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    jobs = db.execute(stmt).scalars().all()
    return [TranscriptionJobResponse.model_validate(j) for j in jobs]


@router.get("/api/job/{job_id}", response_model=TranscriptionJobResponse)
async def get_job(
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Get a specific transcription job."""
    stmt = (
        select(TranscriptionJob)
        .where(TranscriptionJob.id == job_id)
        .where(TranscriptionJob.user_id == current_user.id)
    )
    job = db.execute(stmt).scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")

    return TranscriptionJobResponse.model_validate(job)
