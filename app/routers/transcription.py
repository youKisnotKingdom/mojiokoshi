import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user, limiter, verify_csrf_token
from app.models import (
    AudioFile,
    AudioSource,
    ChunkRefinementStatus,
    PromptTemplate,
    RecordingSession,
    SpeakerDiarizationStatus,
    Summary,
    SummaryStatus,
    TranscriptionChunk,
    TranscriptionEngine,
    TranscriptionJob,
    TranscriptionStatus,
)
from app.models.user import User
from app.schemas.transcription import TranscriptionJobResponse
from app.services import storage, summarization, transcription, transcript_output
from app.services.speaker_diarization import build_speaker_blocks
from app.services.transcription_access import (
    can_manage_transcription_job,
    can_view_transcription_job,
)
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
        "max_upload_size_bytes": settings.max_upload_size,
        "default_engine": settings.default_transcription_engine,
        "default_whisper_model_size": settings.whisper_model_size,
        "default_language": settings.whisper_language or "ja",
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


def _auto_llm_template_names() -> list[str]:
    return [
        name.strip()
        for name in settings.auto_llm_prompt_template_names.split(",")
        if name.strip()
    ]


def _auto_llm_processing_enabled() -> bool:
    return bool(_auto_llm_template_names())


def _auto_llm_templates_available(db: Session) -> bool:
    template_names = _auto_llm_template_names()
    if not template_names:
        return False

    active_template_names = list(db.execute(
        select(PromptTemplate.name).where(PromptTemplate.is_active.is_(True))
    ).scalars())
    return any(
        summarization.template_names_match(configured_name, active_name)
        for configured_name in template_names
        for active_name in active_template_names
    )


def _load_summaries_for_job(db: Session, job_id: uuid.UUID) -> list[Summary]:
    stmt = (
        select(Summary)
        .options(joinedload(Summary.prompt_template))
        .where(Summary.transcription_job_id == job_id)
        .order_by(Summary.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def _duration_seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None:
        return None
    effective_end = end or utc_now()
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if effective_end.tzinfo is None:
        effective_end = effective_end.replace(tzinfo=timezone.utc)
    return max(0.0, (effective_end - start).total_seconds())


def _summary_processing_stats(summaries: list[Summary]) -> dict[str, object]:
    counts = {status.value: 0 for status in SummaryStatus}
    for summary in summaries:
        counts[summary.status.value] = counts.get(summary.status.value, 0) + 1

    first_created_at = min((summary.created_at for summary in summaries), default=None)
    first_started_at = min(
        (summary.started_at for summary in summaries if summary.started_at),
        default=None,
    )
    last_completed_at = max(
        (summary.completed_at for summary in summaries if summary.completed_at),
        default=None,
    )
    active = counts["pending"] + counts["processing"]
    elapsed_start = first_started_at or first_created_at
    elapsed_end = None if active else last_completed_at
    return {
        "total": len(summaries),
        "pending": counts["pending"],
        "processing": counts["processing"],
        "completed": counts["completed"],
        "failed": counts["failed"],
        "active": active,
        "is_active": active > 0,
        "first_created_at": first_created_at,
        "first_started_at": first_started_at,
        "last_completed_at": last_completed_at,
        "elapsed_seconds": _duration_seconds(elapsed_start, elapsed_end),
    }


def _chunk_refinement_stats(db: Session, job_id: uuid.UUID) -> dict[str, object]:
    rows = db.execute(
        select(TranscriptionChunk.refinement_status, func.count(TranscriptionChunk.id))
        .where(TranscriptionChunk.transcription_job_id == job_id)
        .group_by(TranscriptionChunk.refinement_status)
    ).all()
    counts = {status.value: 0 for status in ChunkRefinementStatus}
    for status, count in rows:
        key = status.value if isinstance(status, ChunkRefinementStatus) else str(status)
        counts[key] = int(count)

    total = sum(counts.values())
    active = counts["pending"] + counts["processing"]
    done = counts["completed"] + counts["failed"] + counts["skipped"]
    first_created_at, first_started_at, last_completed_at = db.execute(
        select(
            func.min(TranscriptionChunk.created_at),
            func.min(TranscriptionChunk.refinement_started_at),
            func.max(TranscriptionChunk.refinement_completed_at),
        ).where(TranscriptionChunk.transcription_job_id == job_id)
    ).one()
    elapsed_start = first_started_at or first_created_at
    elapsed_end = None if active else last_completed_at
    return {
        "total": total,
        "pending": counts["pending"],
        "processing": counts["processing"],
        "completed": counts["completed"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "done": done,
        "active": active,
        "percent": int(round((done / total) * 100)) if total else 0,
        "is_active": active > 0,
        "first_created_at": first_created_at,
        "first_started_at": first_started_at,
        "last_completed_at": last_completed_at,
        "elapsed_seconds": _duration_seconds(elapsed_start, elapsed_end),
    }


def _progressive_refined_chunks(job: TranscriptionJob) -> list[dict[str, object]]:
    """Return completed per-chunk LLM outputs for progressive display."""
    chunks: list[dict[str, object]] = []
    for chunk in job.chunks:
        if chunk.refinement_status != ChunkRefinementStatus.COMPLETED:
            continue
        text = (chunk.refined_text or "").strip()
        if not text:
            continue
        chunks.append(
            {
                "start_seconds": chunk.start_seconds,
                "end_seconds": chunk.end_seconds,
                "text": text,
            }
        )
    return chunks


def _progressive_refined_text(chunks: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for chunk in chunks:
        text = str(chunk["text"]).strip()
        if not text:
            continue
        start = transcript_output.format_timecode(chunk.get("start_seconds", 0.0))
        end = transcript_output.format_timecode(chunk.get("end_seconds", 0.0))
        lines.append(f"[{start} - {end}] {text}")
    return "\n\n".join(lines)


def _summary_uses_chunk_refinement(summary: Summary) -> bool:
    metadata = summary.token_usage or {}
    if metadata.get("source") == "chunk_refinement":
        return True
    template_name = summary.prompt_template.name.strip() if summary.prompt_template else ""
    return summarization.template_names_match(
        summarization.REFINED_TRANSCRIPT_TEMPLATE_NAME,
        template_name,
    )


def _summary_display_rows(
    summaries: list[Summary],
    chunk_refinement_stats: dict[str, object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for summary in summaries:
        summary_meta = summary.token_usage or {}
        summary_title = summary.prompt_template.name.strip() if summary.prompt_template else "標準テンプレート"
        uses_chunk_refinement = _summary_uses_chunk_refinement(summary)

        display_started_at = summary.started_at
        display_completed_at = summary.completed_at
        if uses_chunk_refinement and chunk_refinement_stats.get("total"):
            display_started_at = chunk_refinement_stats.get("first_started_at") or summary.started_at
            display_completed_at = (
                None
                if chunk_refinement_stats.get("is_active")
                else chunk_refinement_stats.get("last_completed_at") or summary.completed_at
            )

        rows.append(
            {
                "summary": summary,
                "title": summary_title,
                "meta": summary_meta,
                "uses_chunk_refinement": uses_chunk_refinement,
                "started_at": display_started_at,
                "completed_at": display_completed_at,
            }
        )
    return rows


def _llm_processing_is_active(
    job: TranscriptionJob,
    summaries: list[Summary],
    auto_llm_templates_available: bool,
    chunk_refinement_stats: dict[str, int | bool] | None = None,
) -> bool:
    if job.status in (TranscriptionStatus.PENDING, TranscriptionStatus.PROCESSING):
        return True
    if job.status != TranscriptionStatus.COMPLETED:
        return False
    if chunk_refinement_stats and chunk_refinement_stats.get("is_active"):
        return True
    if not summaries:
        return auto_llm_templates_available
    return any(
        summary.status in (SummaryStatus.PENDING, SummaryStatus.PROCESSING)
        for summary in summaries
    )


def _attachment_headers(filename: str) -> dict[str, str]:
    return {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
    }


def _audio_file_available(audio_file: AudioFile | None) -> bool:
    if audio_file is None or audio_file.is_deleted:
        return False
    if audio_file.expires_at is not None:
        expires_at = audio_file.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= utc_now():
            return False
    return Path(audio_file.file_path).is_file()


def _get_user_job(
    db: Session,
    job_id: uuid.UUID,
    current_user: User,
) -> TranscriptionJob:
    stmt = (
        select(TranscriptionJob)
        .options(
            joinedload(TranscriptionJob.audio_file),
            joinedload(TranscriptionJob.chunks),
            joinedload(TranscriptionJob.user),
        )
        .where(TranscriptionJob.id == job_id)
    )
    job = db.execute(stmt).unique().scalar_one_or_none()
    if not can_view_transcription_job(current_user, job):
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return job


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


@router.get("")
async def transcription_page(
    _current_user: Annotated[User, Depends(get_current_user)],
):
    """Legacy transcription entry: upload is the primary production flow."""
    return RedirectResponse(url="/transcription/upload", status_code=303)


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
    language: Annotated[str | None, Form()] = settings.whisper_language,
    enable_speaker_diarization: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str, Form()] = "",
):
    """Handle file upload and create transcription job."""
    diarization_requested = settings.enable_speaker_diarization and bool(enable_speaker_diarization)

    if not verify_csrf_token(csrf_token):
        return _upload_error_response(
            request,
            current_user,
            "CSRFトークンが無効です。ページを再読み込みして再試行してください。",
            status_code=status.HTTP_403_FORBIDDEN,
            speaker_diarization_requested=diarization_requested,
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
            f"無効なファイル形式です: {file.content_type}。音声または動画ファイルをアップロードしてください。",
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
        transcription_engine = TranscriptionEngine(settings.default_transcription_engine)
    except ValueError:
        transcription_engine = TranscriptionEngine.PARAKEET_JA

    effective_model_size = transcription.model_size_for_engine(
        transcription_engine,
        settings.whisper_model_size,
    )
    effective_language = language if language else None

    job = TranscriptionJob(
        audio_file_id=audio_file.id,
        user_id=current_user.id,
        engine=transcription_engine,
        model_size=effective_model_size,
        language=effective_language,
        enable_speaker_diarization=diarization_requested,
        speaker_diarization_status=(
            SpeakerDiarizationStatus.PENDING
            if diarization_requested
            else SpeakerDiarizationStatus.NOT_REQUESTED
        ),
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
    job = _get_user_job(db, job_id, current_user)

    # Get summaries for this job
    summaries = _load_summaries_for_job(db, job_id)
    auto_llm_templates_available = _auto_llm_templates_available(db)
    chunk_refinement_stats = _chunk_refinement_stats(db, job_id)
    summary_processing_stats = _summary_processing_stats(summaries)
    progressive_refined_chunks = _progressive_refined_chunks(job)

    prompt_template_stmt = (
        select(PromptTemplate)
        .where(PromptTemplate.is_active.is_(True))
        .order_by(PromptTemplate.name)
    )
    prompt_templates = db.execute(prompt_template_stmt).scalars().all()

    history_url = _history_url_for_source(job.audio_file.source if job.audio_file else None)
    speaker_blocks = build_speaker_blocks(job.result_segments if isinstance(job.result_segments, list) else None)
    audio_available = _audio_file_available(job.audio_file)
    audio_is_video = bool(
        audio_available
        and job.audio_file
        and (job.audio_file.mime_type or "").startswith("video/")
    )

    return templates.TemplateResponse(
        "transcription/job_detail.html",
        {
            "request": request,
            "title": "文字起こしジョブ",
            "current_user": current_user,
            "job": job,
            "summaries": summaries,
            "summary_display_rows": _summary_display_rows(summaries, chunk_refinement_stats),
            "llm_processing_active": _llm_processing_is_active(
                job,
                summaries,
                auto_llm_templates_available,
                chunk_refinement_stats,
            ),
            "chunk_refinement_stats": chunk_refinement_stats,
            "summary_processing_stats": summary_processing_stats,
            "progressive_refined_chunks": progressive_refined_chunks,
            "progressive_refined_text": _progressive_refined_text(progressive_refined_chunks),
            "auto_llm_processing_enabled": _auto_llm_processing_enabled(),
            "auto_llm_templates_available": auto_llm_templates_available,
            "auto_llm_template_names": _auto_llm_template_names(),
            "prompt_templates": prompt_templates,
            "history_url": history_url,
            "speaker_blocks": speaker_blocks,
            "speaker_text": transcript_output.build_speaker_text(job),
            "transcript_text_with_timecodes": transcript_output.build_chunked_transcript_text(
                job,
                fallback_to_result=False,
            ),
            "audio_available": audio_available,
            "audio_is_video": audio_is_video,
            "show_next_actions": settings.show_next_actions,
            "can_manage_job": can_manage_transcription_job(current_user, job),
            "speaker_diarization_requested": job.enable_speaker_diarization,
            "speaker_diarization_enabled": settings.enable_speaker_diarization,
        },
    )


@router.get("/job/{job_id}/llm-processing-progress", response_class=HTMLResponse)
async def llm_processing_progress_partial(
    request: Request,
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """HTMX partial for LLM post-processing status tied to a transcription job."""
    job = _get_user_job(db, job_id, current_user)
    summaries = _load_summaries_for_job(db, job_id)
    auto_llm_templates_available = _auto_llm_templates_available(db)
    chunk_refinement_stats = _chunk_refinement_stats(db, job_id)
    summary_processing_stats = _summary_processing_stats(summaries)
    progressive_refined_chunks = _progressive_refined_chunks(job)
    audio_available = _audio_file_available(job.audio_file)
    return templates.TemplateResponse(
        "transcription/partials/llm_processing_progress.html",
        {
            "request": request,
            "job": job,
            "summaries": summaries,
            "summary_display_rows": _summary_display_rows(summaries, chunk_refinement_stats),
            "llm_processing_active": _llm_processing_is_active(
                job,
                summaries,
                auto_llm_templates_available,
                chunk_refinement_stats,
            ),
            "chunk_refinement_stats": chunk_refinement_stats,
            "summary_processing_stats": summary_processing_stats,
            "progressive_refined_chunks": progressive_refined_chunks,
            "progressive_refined_text": _progressive_refined_text(progressive_refined_chunks),
            "auto_llm_processing_enabled": _auto_llm_processing_enabled(),
            "auto_llm_templates_available": auto_llm_templates_available,
            "auto_llm_template_names": _auto_llm_template_names(),
            "audio_available": audio_available,
            "show_next_actions": settings.show_next_actions,
            "can_manage_job": can_manage_transcription_job(current_user, job),
        },
    )


@router.get("/job/{job_id}/audio")
async def stream_job_audio(
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Stream the source audio/video for timestamp review while the file is retained."""
    job = _get_user_job(db, job_id, current_user)
    audio_file = job.audio_file
    if not _audio_file_available(audio_file):
        raise HTTPException(status_code=404, detail="音声ファイルは利用できません")

    return FileResponse(
        Path(audio_file.file_path),
        media_type=audio_file.mime_type or "application/octet-stream",
        filename=audio_file.original_filename,
        content_disposition_type="inline",
    )


@router.get("/job/{job_id}/download/{export_format}")
async def download_job_result(
    job_id: uuid.UUID,
    export_format: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Download transcription results as txt, speaker-txt, vtt, or json."""
    job = _get_user_job(db, job_id, current_user)
    if job.status != TranscriptionStatus.COMPLETED or not job.result_text:
        raise HTTPException(status_code=400, detail="文字起こしが完了していません")

    stem = transcript_output.safe_download_stem(job)
    if export_format == "txt":
        content = transcript_output.build_chunked_transcript_text(job)
        media_type = "text/plain; charset=utf-8"
        filename = f"{stem}.txt"
    elif export_format == "speaker-txt":
        content = transcript_output.build_speaker_text(job)
        media_type = "text/plain; charset=utf-8"
        filename = f"{stem}-speakers.txt"
    elif export_format == "vtt":
        content = transcript_output.build_webvtt(job)
        media_type = "text/vtt; charset=utf-8"
        filename = f"{stem}.vtt"
    elif export_format == "json":
        content = transcript_output.build_result_json(job)
        media_type = "application/json; charset=utf-8"
        filename = f"{stem}.json"
    else:
        raise HTTPException(status_code=404, detail="未対応のダウンロード形式です")

    return Response(
        content=content,
        media_type=media_type,
        headers=_attachment_headers(filename),
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
        .options(joinedload(TranscriptionJob.audio_file))
        .where(TranscriptionJob.id == job_id)
    )
    job = db.execute(stmt).scalar_one_or_none()

    if not can_view_transcription_job(current_user, job):
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
        .options(joinedload(TranscriptionJob.audio_file))
        .where(TranscriptionJob.id == job_id)
    )
    job = db.execute(stmt).scalar_one_or_none()
    if not can_manage_transcription_job(current_user, job):
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")

    redirect_url = next_url if _is_safe_internal_url(next_url) else _history_url_for_source(job.audio_file.source if job.audio_file else None)

    # Delete associated audio file (cascades to job, chunks, and summaries).
    if job.audio_file:
        audio_file = job.audio_file
        # Try to remove the actual file
        import os
        try:
            if os.path.exists(audio_file.file_path):
                os.remove(audio_file.file_path)
        except OSError:
            pass
        db.query(RecordingSession).filter(RecordingSession.audio_file_id == audio_file.id).delete(
            synchronize_session=False
        )
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
    )
    job = db.execute(stmt).scalar_one_or_none()

    if not can_view_transcription_job(current_user, job):
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")

    return TranscriptionJobResponse.model_validate(job)
