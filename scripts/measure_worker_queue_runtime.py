#!/usr/bin/env python3
"""Measure queue drain time with externally running worker containers."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

from sqlalchemy import func, select

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


def _create_jobs(audio_path: str, jobs: int, engine: TranscriptionEngine, model_size: str) -> tuple[list[str], list[str]]:
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
                stored_filename=f"ops-queue-{i}-{audio_path_obj.name}",
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--jobs", type=int, default=5)
    parser.add_argument("--engine", default=settings.default_transcription_engine, choices=[engine.value for engine in TranscriptionEngine])
    parser.add_argument("--model-size")
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    engine = TranscriptionEngine(args.engine)
    model_size = _resolve_model_size(engine, args.model_size)

    audio_ids, job_ids = _create_jobs(args.audio, args.jobs, engine, model_size)
    try:
        started = time.perf_counter()
        deadline = started + args.timeout
        while time.perf_counter() < deadline:
            db = SessionLocal()
            try:
                active = db.scalar(
                    select(func.count())
                    .select_from(TranscriptionJob)
                    .where(TranscriptionJob.id.in_(job_ids))
                    .where(TranscriptionJob.status.in_([TranscriptionStatus.PENDING, TranscriptionStatus.PROCESSING]))
                ) or 0
            finally:
                db.close()
            if active == 0:
                break
            time.sleep(args.poll_interval)

        elapsed = time.perf_counter() - started
        jobs = _fetch_jobs(job_ids)
        report = {
            "audio": args.audio,
            "jobs_requested": args.jobs,
            "poll_interval": args.poll_interval,
            "timeout": args.timeout,
            "elapsed_seconds": round(elapsed, 3),
            "timed_out": any(job["status"] in {"pending", "processing"} for job in jobs),
            "settings": {
                "default_transcription_engine": settings.default_transcription_engine,
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
