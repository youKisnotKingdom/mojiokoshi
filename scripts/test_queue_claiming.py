#!/usr/bin/env python3
"""Reproduce queue-claim behavior with and without FOR UPDATE SKIP LOCKED."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AudioFile, AudioSource, TranscriptionEngine, TranscriptionJob, TranscriptionStatus
from app.time_utils import utc_now

TAG = "queue-claim-test-20260421"
OUTPUT = Path("benchmark_runs/queue_claim_test_20260421.json")


def _create_test_jobs() -> tuple[list[str], list[str]]:
    db = SessionLocal()
    audio_ids: list[str] = []
    job_ids: list[str] = []
    try:
        base_time = utc_now()
        for i in range(2):
            audio = AudioFile(
                id=uuid.uuid4(),
                user_id=1,
                source=AudioSource.UPLOAD,
                original_filename=f"{TAG}-{i}.wav",
                stored_filename=f"{TAG}-{i}.wav",
                file_path=f"/tmp/{TAG}-{i}.wav",
                file_size=1,
                mime_type="audio/wav",
                duration_seconds=60,
                created_at=base_time,
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
                created_at=base_time,
            )
            db.add(job)
            audio_ids.append(str(audio.id))
            job_ids.append(str(job.id))
            base_time = base_time.replace(microsecond=min(999999, base_time.microsecond + 1))
        db.commit()
        return audio_ids, job_ids
    finally:
        db.close()


def _cleanup(job_ids: list[str], audio_ids: list[str]) -> None:
    db = SessionLocal()
    try:
        db.execute(TranscriptionJob.__table__.delete().where(TranscriptionJob.id.in_(job_ids)))
        db.execute(AudioFile.__table__.delete().where(AudioFile.id.in_(audio_ids)))
        db.commit()
    finally:
        db.close()


def _plain_claim(job_ids: list[str]) -> dict:
    s1 = SessionLocal()
    s2 = SessionLocal()
    try:
        stmt = (
            select(TranscriptionJob.id)
            .where(TranscriptionJob.id.in_(job_ids))
            .where(TranscriptionJob.status == TranscriptionStatus.PENDING)
            .order_by(TranscriptionJob.created_at)
            .limit(1)
        )
        picked1 = str(s1.execute(stmt).scalar_one())
        picked2 = str(s2.execute(stmt).scalar_one())
        return {"worker1": picked1, "worker2": picked2, "duplicate": picked1 == picked2}
    finally:
        s1.close()
        s2.close()


def _skip_locked_claim(job_ids: list[str]) -> dict:
    s1 = SessionLocal()
    s2 = SessionLocal()
    tx1 = s1.begin()
    tx2 = s2.begin()
    try:
        stmt = (
            select(TranscriptionJob.id)
            .where(TranscriptionJob.id.in_(job_ids))
            .where(TranscriptionJob.status == TranscriptionStatus.PENDING)
            .order_by(TranscriptionJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        picked1 = str(s1.execute(stmt).scalar_one())
        picked2 = str(s2.execute(stmt).scalar_one())
        return {"worker1": picked1, "worker2": picked2, "duplicate": picked1 == picked2}
    finally:
        tx2.rollback()
        tx1.rollback()
        s2.close()
        s1.close()


def main() -> None:
    audio_ids, job_ids = _create_test_jobs()
    try:
        plain = _plain_claim(job_ids)
        locked = _skip_locked_claim(job_ids)
        report = {
            "tag": TAG,
            "job_ids": job_ids,
            "plain_select": plain,
            "for_update_skip_locked": locked,
            "summary": {
                "plain_duplicates": plain["duplicate"],
                "skip_locked_duplicates": locked["duplicate"],
            },
        }
        OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        _cleanup(job_ids, audio_ids)


if __name__ == "__main__":
    main()
