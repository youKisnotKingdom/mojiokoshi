"""
Cleanup service for automatic deletion of expired audio files.
"""
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AudioFile

settings = get_settings()
logger = logging.getLogger(__name__)


def get_expired_audio_files(db: Session, limit: int = 100) -> list[AudioFile]:
    """Get audio files that have passed their expiration date."""
    now = datetime.now()
    stmt = (
        select(AudioFile)
        .where(AudioFile.expires_at <= now)
        .where(AudioFile.deleted_at.is_(None))
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def delete_audio_file(db: Session, audio_file: AudioFile) -> bool:
    """
    Delete an audio file from storage and mark as deleted in database.

    Note: Only the audio file is deleted. Transcription text and summaries are kept.
    """
    try:
        # Delete physical file
        file_path = Path(audio_file.file_path)
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Deleted file: {file_path}")

        # Mark as deleted in database (soft delete)
        audio_file.deleted_at = datetime.now()
        db.commit()

        logger.info(f"Marked audio file {audio_file.id} as deleted")
        return True

    except Exception as e:
        logger.error(f"Failed to delete audio file {audio_file.id}: {e}")
        db.rollback()
        return False


def cleanup_expired_files(db: Session, batch_size: int = 50) -> tuple[int, int]:
    """
    Clean up expired audio files.

    Returns:
        Tuple of (deleted_count, failed_count)
    """
    expired_files = get_expired_audio_files(db, limit=batch_size)
    deleted = 0
    failed = 0

    for audio_file in expired_files:
        if delete_audio_file(db, audio_file):
            deleted += 1
        else:
            failed += 1

    if deleted > 0:
        logger.info(f"Cleanup complete: {deleted} files deleted, {failed} failed")

    return deleted, failed


def cleanup_orphaned_chunks(db: Session) -> int:
    """
    Clean up orphaned recording chunks (chunks without completed sessions).
    """
    from app.models import RecordingChunk, RecordingSession, RecordingStatus

    # Find chunks from sessions that are not completed and older than 24 hours
    cutoff = datetime.now()
    from datetime import timedelta
    cutoff = cutoff - timedelta(hours=24)

    # Get orphaned sessions
    stmt = (
        select(RecordingSession)
        .where(RecordingSession.status != RecordingStatus.COMPLETED)
        .where(RecordingSession.started_at < cutoff)
    )
    orphaned_sessions = db.execute(stmt).scalars().all()

    deleted_count = 0
    for session in orphaned_sessions:
        # Delete chunk files
        chunk_stmt = select(RecordingChunk).where(RecordingChunk.session_id == session.id)
        chunks = db.execute(chunk_stmt).scalars().all()

        for chunk in chunks:
            try:
                file_path = Path(chunk.file_path)
                if file_path.exists():
                    file_path.unlink()
                db.delete(chunk)
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete chunk {chunk.id}: {e}")

        # Delete session
        db.delete(session)

    db.commit()

    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} orphaned chunks")

    return deleted_count


def cleanup_empty_directories(base_dir: str | Path) -> int:
    """
    Clean up empty directories in the upload directory structure.
    """
    base_path = Path(base_dir)
    if not base_path.exists():
        return 0

    deleted = 0
    # Walk bottom-up to remove empty directories
    for dirpath in sorted(base_path.rglob("*"), reverse=True):
        if dirpath.is_dir():
            try:
                dirpath.rmdir()  # Only succeeds if empty
                deleted += 1
                logger.debug(f"Removed empty directory: {dirpath}")
            except OSError:
                pass  # Directory not empty

    return deleted


async def run_cleanup_job():
    """Run the full cleanup job."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        logger.info("Starting cleanup job")

        # Clean expired audio files
        deleted, failed = cleanup_expired_files(db)

        # Clean orphaned chunks
        orphaned = cleanup_orphaned_chunks(db)

        # Clean empty directories
        empty_dirs = cleanup_empty_directories(settings.upload_dir)

        logger.info(
            f"Cleanup complete: {deleted} files deleted, {failed} failed, "
            f"{orphaned} orphaned chunks, {empty_dirs} empty directories"
        )

    except Exception as e:
        logger.error(f"Cleanup job failed: {e}")
    finally:
        db.close()
