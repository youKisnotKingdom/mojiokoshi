"""Operational dashboard helpers for queue visibility and manual recovery."""
from __future__ import annotations

from datetime import timedelta
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models import Summary, SummaryStatus, TranscriptionJob, TranscriptionStatus
from app.time_utils import utc_now

settings = get_settings()


def _age_seconds(timestamp) -> float | None:
    if not timestamp:
        return None
    return round((utc_now() - timestamp).total_seconds(), 1)


def _status_counts(db: Session, model, enum_cls) -> dict[str, int]:
    counts = {status.value: 0 for status in enum_cls}
    rows = db.execute(select(model.status, func.count()).group_by(model.status)).all()
    for status, count in rows:
        counts[status.value] = count
    counts["total"] = sum(counts.values())
    return counts


def _serialize_transcription_job(job: TranscriptionJob) -> dict[str, object]:
    return {
        "id": str(job.id),
        "status": job.status.value,
        "engine": job.engine.value,
        "model_size": job.model_size,
        "enable_speaker_diarization": job.enable_speaker_diarization,
        "user_display_name": job.user.display_name if job.user else None,
        "original_filename": job.audio_file.original_filename if job.audio_file else None,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "pending_age_seconds": _age_seconds(job.created_at) if job.status == TranscriptionStatus.PENDING else None,
        "processing_age_seconds": _age_seconds(job.started_at) if job.status == TranscriptionStatus.PROCESSING else None,
        "error_message": job.error_message,
        "progress_percent": job.progress_percent,
    }


def _serialize_summary(summary: Summary) -> dict[str, object]:
    filename = None
    if summary.transcription_job and summary.transcription_job.audio_file:
        filename = summary.transcription_job.audio_file.original_filename

    return {
        "id": str(summary.id),
        "status": summary.status.value,
        "user_display_name": summary.user.display_name if summary.user else None,
        "transcription_job_id": str(summary.transcription_job_id),
        "original_filename": filename,
        "created_at": summary.created_at,
        "started_at": summary.started_at,
        "completed_at": summary.completed_at,
        "pending_age_seconds": _age_seconds(summary.created_at) if summary.status == SummaryStatus.PENDING else None,
        "processing_age_seconds": _age_seconds(summary.started_at) if summary.status == SummaryStatus.PROCESSING else None,
        "error_message": summary.error_message,
    }


def build_operations_snapshot(db: Session) -> dict[str, object]:
    now = utc_now()

    transcription_pending_stmt = (
        select(TranscriptionJob)
        .options(joinedload(TranscriptionJob.audio_file), joinedload(TranscriptionJob.user))
        .where(TranscriptionJob.status == TranscriptionStatus.PENDING)
        .order_by(TranscriptionJob.created_at)
        .limit(10)
    )
    transcription_processing_stmt = (
        select(TranscriptionJob)
        .options(joinedload(TranscriptionJob.audio_file), joinedload(TranscriptionJob.user))
        .where(TranscriptionJob.status == TranscriptionStatus.PROCESSING)
        .order_by(TranscriptionJob.started_at)
        .limit(10)
    )
    transcription_failed_stmt = (
        select(TranscriptionJob)
        .options(joinedload(TranscriptionJob.audio_file), joinedload(TranscriptionJob.user))
        .where(TranscriptionJob.status == TranscriptionStatus.FAILED)
        .order_by(TranscriptionJob.completed_at.desc().nullslast(), TranscriptionJob.created_at.desc())
        .limit(10)
    )

    summary_pending_stmt = (
        select(Summary)
        .options(joinedload(Summary.user), joinedload(Summary.transcription_job).joinedload(TranscriptionJob.audio_file))
        .where(Summary.status == SummaryStatus.PENDING)
        .order_by(Summary.created_at)
        .limit(10)
    )
    summary_processing_stmt = (
        select(Summary)
        .options(joinedload(Summary.user), joinedload(Summary.transcription_job).joinedload(TranscriptionJob.audio_file))
        .where(Summary.status == SummaryStatus.PROCESSING)
        .order_by(Summary.started_at)
        .limit(10)
    )
    summary_failed_stmt = (
        select(Summary)
        .options(joinedload(Summary.user), joinedload(Summary.transcription_job).joinedload(TranscriptionJob.audio_file))
        .where(Summary.status == SummaryStatus.FAILED)
        .order_by(Summary.completed_at.desc().nullslast(), Summary.created_at.desc())
        .limit(10)
    )

    transcription_pending = list(db.execute(transcription_pending_stmt).unique().scalars().all())
    transcription_processing = list(db.execute(transcription_processing_stmt).unique().scalars().all())
    transcription_failed = list(db.execute(transcription_failed_stmt).unique().scalars().all())
    summary_pending = list(db.execute(summary_pending_stmt).unique().scalars().all())
    summary_processing = list(db.execute(summary_processing_stmt).unique().scalars().all())
    summary_failed = list(db.execute(summary_failed_stmt).unique().scalars().all())

    transcription_stale_count = 0
    if settings.worker_transcription_stale_timeout_seconds > 0:
        cutoff = now - timedelta(seconds=settings.worker_transcription_stale_timeout_seconds)
        transcription_stale_count = db.scalar(
            select(func.count())
            .select_from(TranscriptionJob)
            .where(TranscriptionJob.status == TranscriptionStatus.PROCESSING)
            .where(TranscriptionJob.started_at.is_not(None))
            .where(TranscriptionJob.started_at < cutoff)
        ) or 0

    summary_stale_count = 0
    if settings.worker_summary_stale_timeout_seconds > 0:
        cutoff = now - timedelta(seconds=settings.worker_summary_stale_timeout_seconds)
        summary_stale_count = db.scalar(
            select(func.count())
            .select_from(Summary)
            .where(Summary.status == SummaryStatus.PROCESSING)
            .where(Summary.started_at.is_not(None))
            .where(Summary.started_at < cutoff)
        ) or 0

    return {
        "captured_at": now,
        "worker": {
            "default_transcription_engine": settings.default_transcription_engine,
            "whisper_device": settings.whisper_device,
            "enable_realtime_transcription": settings.enable_realtime_transcription,
            "enable_speaker_diarization": settings.enable_speaker_diarization,
            "worker_poll_interval": settings.worker_poll_interval,
            "worker_transcription_concurrency": settings.worker_transcription_concurrency,
            "worker_summary_concurrency": settings.worker_summary_concurrency,
            "worker_transcription_stale_timeout_seconds": settings.worker_transcription_stale_timeout_seconds,
            "worker_summary_stale_timeout_seconds": settings.worker_summary_stale_timeout_seconds,
            "max_upload_size_bytes": settings.max_upload_size,
        },
        "transcriptions": {
            "counts": _status_counts(db, TranscriptionJob, TranscriptionStatus),
            "oldest_pending_age_seconds": _age_seconds(transcription_pending[0].created_at) if transcription_pending else None,
            "stale_processing_count": transcription_stale_count,
            "pending_jobs": [_serialize_transcription_job(job) for job in transcription_pending],
            "processing_jobs": [_serialize_transcription_job(job) for job in transcription_processing],
            "failed_jobs": [_serialize_transcription_job(job) for job in transcription_failed],
        },
        "summaries": {
            "counts": _status_counts(db, Summary, SummaryStatus),
            "oldest_pending_age_seconds": _age_seconds(summary_pending[0].created_at) if summary_pending else None,
            "stale_processing_count": summary_stale_count,
            "pending_jobs": [_serialize_summary(summary) for summary in summary_pending],
            "processing_jobs": [_serialize_summary(summary) for summary in summary_processing],
            "failed_jobs": [_serialize_summary(summary) for summary in summary_failed],
        },
    }


def requeue_transcription_job(db: Session, job_id: uuid.UUID) -> TranscriptionJob | None:
    stmt = select(TranscriptionJob).where(TranscriptionJob.id == job_id).with_for_update()
    job = db.execute(stmt).scalar_one_or_none()
    if not job:
        return None
    if job.status == TranscriptionStatus.COMPLETED:
        raise ValueError("completed transcription job cannot be re-queued")

    job.status = TranscriptionStatus.PENDING
    job.started_at = None
    job.completed_at = None
    job.progress_percent = 0.0
    job.result_text = None
    job.result_segments = None
    job.error_message = None
    db.commit()
    db.refresh(job)
    return job


def requeue_summary_job(db: Session, summary_id: uuid.UUID) -> Summary | None:
    stmt = select(Summary).where(Summary.id == summary_id).with_for_update()
    summary = db.execute(stmt).scalar_one_or_none()
    if not summary:
        return None
    if summary.status == SummaryStatus.COMPLETED:
        raise ValueError("completed summary cannot be re-queued")

    summary.status = SummaryStatus.PENDING
    summary.started_at = None
    summary.completed_at = None
    summary.result_text = None
    summary.token_usage = None
    summary.error_message = None
    db.commit()
    db.refresh(summary)
    return summary
