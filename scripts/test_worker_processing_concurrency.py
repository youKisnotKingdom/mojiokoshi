#!/usr/bin/env python3
"""Measure actual worker processing behavior for multiple jobs."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import AudioFile, AudioSource, TranscriptionEngine, TranscriptionJob, TranscriptionStatus
from app.services import transcription
from app.time_utils import utc_now

settings = get_settings()


def _resolve_model_size(engine: TranscriptionEngine, model_size: str | None) -> str:
    if model_size:
        return model_size
    if engine == TranscriptionEngine.PARAKEET_JA:
        return transcription.PARAKEET_JA_REPO_ID
    return settings.whisper_model_size


def _create_jobs(
    audio_path: str,
    jobs: int,
    engine: TranscriptionEngine,
    model_size: str,
) -> tuple[list[str], list[str]]:
    db = SessionLocal()
    audio_ids: list[str] = []
    job_ids: list[str] = []
    try:
        now = utc_now()
        audio_path_obj = Path(audio_path)
        file_size = audio_path_obj.stat().st_size
        for i in range(jobs):
            audio = AudioFile(
                id=uuid.uuid4(),
                user_id=1,
                source=AudioSource.UPLOAD,
                original_filename=audio_path_obj.name,
                stored_filename=f"ops-test-{i}-{audio_path_obj.name}",
                file_path=audio_path,
                file_size=file_size,
                mime_type="audio/wav",
                duration_seconds=None,
                created_at=now,
            )
            db.add(audio)
            db.flush()
            job = TranscriptionJob(
                id=uuid.uuid4(),
                audio_file_id=audio.id,
                user_id=1,
                status=TranscriptionStatus.PENDING,
                engine=engine,
                model_size=model_size,
                progress_percent=0.0,
                created_at=now,
            )
            db.add(job)
            audio_ids.append(str(audio.id))
            job_ids.append(str(job.id))
        db.commit()
        return audio_ids, job_ids
    finally:
        db.close()


def _cleanup(audio_ids: list[str], job_ids: list[str]) -> None:
    db = SessionLocal()
    try:
        db.execute(TranscriptionJob.__table__.delete().where(TranscriptionJob.id.in_(job_ids)))
        db.execute(AudioFile.__table__.delete().where(AudioFile.id.in_(audio_ids)))
        db.commit()
    finally:
        db.close()


def _fetch_jobs(job_ids: list[str]) -> list[dict]:
    db = SessionLocal()
    try:
        jobs = [db.get(TranscriptionJob, job_id) for job_id in job_ids]
        result = []
        for job in jobs:
            if not job:
                continue
            result.append(
                {
                    "job_id": str(job.id),
                    "status": job.status.value,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                    "error_message": job.error_message,
                    "result_text_length": len(job.result_text or ""),
                }
            )
        return result
    finally:
        db.close()


async def _run_until_empty(concurrency: int, poll_interval: float) -> int:
    raise NotImplementedError


def _claim_test_jobs(job_ids: list[str], limit: int) -> list[uuid.UUID]:
    db = SessionLocal()
    try:
        stmt = (
            select(TranscriptionJob)
            .where(TranscriptionJob.id.in_(job_ids))
            .where(TranscriptionJob.status == TranscriptionStatus.PENDING)
            .order_by(TranscriptionJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        jobs = list(db.execute(stmt).scalars().all())
        if not jobs:
            return []
        now = utc_now()
        claimed: list[uuid.UUID] = []
        for job in jobs:
            job.status = TranscriptionStatus.PROCESSING
            job.started_at = now
            job.progress_percent = 0.0
            job.error_message = None
            claimed.append(job.id)
        db.commit()
        return claimed
    finally:
        db.close()


async def _run_until_empty(job_ids: list[str], concurrency: int, poll_interval: float) -> int:
    processed = 0
    while True:
        claimed = _claim_test_jobs(job_ids, limit=concurrency)
        if not claimed:
            break
        await asyncio.gather(
            *[
                transcription.process_transcription_job_by_id(job_id)
                for job_id in claimed
            ]
        )
        processed += len(claimed)
        await asyncio.sleep(poll_interval)
    return processed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True, help="Audio path visible from the container")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--poll-interval", type=float, default=0.1)
    parser.add_argument(
        "--engine",
        default=settings.default_transcription_engine,
        choices=[engine.value for engine in TranscriptionEngine],
    )
    parser.add_argument("--model-size")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    engine = TranscriptionEngine(args.engine)
    model_size = _resolve_model_size(engine, args.model_size)

    audio_ids, job_ids = _create_jobs(args.audio, args.jobs, engine, model_size)
    try:
        started = time.perf_counter()
        processed = asyncio.run(_run_until_empty(job_ids, args.concurrency, args.poll_interval))
        elapsed = time.perf_counter() - started
        jobs = _fetch_jobs(job_ids)
        report = {
            "audio": args.audio,
            "jobs_requested": args.jobs,
            "jobs_processed": processed,
            "concurrency": args.concurrency,
            "poll_interval": args.poll_interval,
            "elapsed_seconds": round(elapsed, 3),
            "settings": {
                "default_transcription_engine": settings.default_transcription_engine,
                "whisper_model_size": settings.whisper_model_size,
                "whisper_device": settings.whisper_device,
                "engine": engine.value,
                "model_size": model_size,
            },
            "jobs": jobs,
        }
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        _cleanup(audio_ids, job_ids)


if __name__ == "__main__":
    main()
