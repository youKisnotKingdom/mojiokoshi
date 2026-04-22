#!/usr/bin/env python3
"""Demonstrate stale-processing recovery for claimed jobs."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from pathlib import Path

from app.database import SessionLocal
from app.models import AudioFile, AudioSource, TranscriptionEngine, TranscriptionJob, TranscriptionStatus
from app.services.transcription import claim_pending_jobs, requeue_stale_processing_jobs
from app.time_utils import utc_now

OUTPUT = Path("benchmark_runs/stale_job_recovery_test_20260422.json")
TAG = "stale-job-test-20260422"


def _create_job() -> tuple[str, str]:
    db = SessionLocal()
    try:
        now = utc_now()
        audio = AudioFile(
            id=uuid.uuid4(),
            user_id=1,
            source=AudioSource.UPLOAD,
            original_filename=f"{TAG}.wav",
            stored_filename=f"{TAG}.wav",
            file_path="/tmp/does-not-matter.wav",
            file_size=1,
            mime_type="audio/wav",
            duration_seconds=30,
            created_at=now,
        )
        db.add(audio)
        db.flush()

        job = TranscriptionJob(
            id=uuid.uuid4(),
            audio_file_id=audio.id,
            user_id=1,
            status=TranscriptionStatus.PENDING,
            engine=TranscriptionEngine.FASTER_WHISPER,
            model_size="medium",
            progress_percent=0.0,
            created_at=now,
        )
        db.add(job)
        db.commit()
        return str(audio.id), str(job.id)
    finally:
        db.close()


def _cleanup(audio_id: str, job_id: str) -> None:
    db = SessionLocal()
    try:
        db.execute(TranscriptionJob.__table__.delete().where(TranscriptionJob.id == job_id))
        db.execute(AudioFile.__table__.delete().where(AudioFile.id == audio_id))
        db.commit()
    finally:
        db.close()


def main() -> None:
    audio_id, job_id = _create_job()
    try:
        db = SessionLocal()
        try:
            claimed = [str(x) for x in claim_pending_jobs(db, limit=1)]
        finally:
            db.close()

        backdate_db = SessionLocal()
        try:
            job = backdate_db.get(TranscriptionJob, job_id)
            if job:
                job.started_at = utc_now() - timedelta(hours=2)
                backdate_db.commit()
        finally:
            backdate_db.close()

        recovery_db = SessionLocal()
        try:
            recovered = [
                str(x) for x in requeue_stale_processing_jobs(recovery_db, stale_after_seconds=60)
            ]
        finally:
            recovery_db.close()

        second_db = SessionLocal()
        try:
            second_claim = [str(x) for x in claim_pending_jobs(second_db, limit=1)]
        finally:
            second_db.close()

        inspect_db = SessionLocal()
        try:
            job = inspect_db.get(TranscriptionJob, job_id)
            report = {
                "tag": TAG,
                "job_id": job_id,
                "first_claim": claimed,
                "recovered_jobs": recovered,
                "second_claim_after_simulated_crash": second_claim,
                "job_status_after_recovery": job.status.value if job else None,
                "started_at_after_recovery": job.started_at.isoformat() if job and job.started_at else None,
                "error_message_after_recovery": job.error_message if job else None,
                "summary": {
                    "recovered_before_reclaim": bool(recovered),
                    "reclaimable_after_recovery": bool(second_claim),
                },
            }
        finally:
            inspect_db.close()

        OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        _cleanup(audio_id, job_id)


if __name__ == "__main__":
    main()
