import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import AudioFile, AudioSource, TranscriptionEngine, TranscriptionJob, TranscriptionStatus
from app.models.user import User
from app.schemas.transcription import TranscriptionJobResponse
from app.services import storage

settings = get_settings()
router = APIRouter(prefix="/transcription", tags=["transcription"])
templates = Jinja2Templates(directory="app/templates")


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
            "title": "Transcription",
            "current_user": current_user,
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
        {
            "request": request,
            "title": "Upload Audio",
            "current_user": current_user,
            "engines": TranscriptionEngine,
        },
    )


@router.post("/upload")
async def upload_file(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    file: Annotated[UploadFile, File()],
    engine: Annotated[str, Form()] = "faster_whisper",
    model_size: Annotated[str, Form()] = "large",
    language: Annotated[str | None, Form()] = None,
):
    """Handle file upload and create transcription job."""
    # Validate file
    if not file.filename:
        return templates.TemplateResponse(
            "transcription/upload.html",
            {
                "request": request,
                "title": "Upload Audio",
                "current_user": current_user,
                "engines": TranscriptionEngine,
                "error": "No file selected",
            },
            status_code=400,
        )

    # Check MIME type
    if not storage.validate_audio_mime_type(file.content_type):
        return templates.TemplateResponse(
            "transcription/upload.html",
            {
                "request": request,
                "title": "Upload Audio",
                "current_user": current_user,
                "engines": TranscriptionEngine,
                "error": f"Invalid file type: {file.content_type}. Please upload an audio file.",
            },
            status_code=400,
        )

    # Read and save file
    content = await file.read()
    if len(content) > settings.max_upload_size:
        return templates.TemplateResponse(
            "transcription/upload.html",
            {
                "request": request,
                "title": "Upload Audio",
                "current_user": current_user,
                "engines": TranscriptionEngine,
                "error": f"File too large. Maximum size is {settings.max_upload_size // 1024 // 1024}MB.",
            },
            status_code=400,
        )

    stored_filename, file_path = await storage.save_upload_file(
        content, file.filename, file.content_type
    )

    # Calculate expiration date
    expires_at = datetime.now() + timedelta(days=settings.audio_retention_days)

    # Create audio file record
    audio_file = AudioFile(
        user_id=current_user.id,
        source=AudioSource.UPLOAD,
        original_filename=file.filename,
        stored_filename=stored_filename,
        file_path=file_path,
        file_size=len(content),
        mime_type=file.content_type,
        expires_at=expires_at,
    )
    db.add(audio_file)
    db.flush()

    # Create transcription job
    try:
        transcription_engine = TranscriptionEngine(engine)
    except ValueError:
        transcription_engine = TranscriptionEngine.FASTER_WHISPER

    job = TranscriptionJob(
        audio_file_id=audio_file.id,
        user_id=current_user.id,
        engine=transcription_engine,
        model_size=model_size,
        language=language if language else None,
    )
    db.add(job)
    db.commit()

    # Redirect to job status page
    from fastapi.responses import RedirectResponse
    return RedirectResponse(
        url=f"/transcription/job/{job.id}",
        status_code=303,
    )


@router.get("/record", response_class=HTMLResponse)
async def record_page(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Recording page."""
    return templates.TemplateResponse(
        "transcription/record.html",
        {
            "request": request,
            "title": "Record Audio",
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
        raise HTTPException(status_code=404, detail="Job not found")

    return templates.TemplateResponse(
        "transcription/job_detail.html",
        {
            "request": request,
            "title": "Transcription Job",
            "current_user": current_user,
            "job": job,
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
        raise HTTPException(status_code=404, detail="Job not found")

    return templates.TemplateResponse(
        "transcription/partials/job_progress.html",
        {
            "request": request,
            "job": job,
        },
    )


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
        raise HTTPException(status_code=404, detail="Job not found")

    return TranscriptionJobResponse.model_validate(job)
