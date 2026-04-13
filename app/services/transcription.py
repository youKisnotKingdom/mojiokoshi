"""
Transcription service using faster-whisper for audio transcription.
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Generator, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import TranscriptionEngine, TranscriptionJob, TranscriptionStatus

settings = get_settings()
logger = logging.getLogger(__name__)

# Lazy-loaded model cache
_whisper_models: dict[str, object] = {}


def get_whisper_model(model_size: str = "medium", device: str = "auto"):
    """
    Get or create a faster-whisper model instance.
    Models are cached to avoid reloading.
    """
    cache_key = f"{model_size}_{device}"
    if cache_key not in _whisper_models:
        try:
            from faster_whisper import WhisperModel

            compute_type = "float16" if device in ("cuda", "auto") else "int8"
            model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
            )
            _whisper_models[cache_key] = model
            logger.info(f"Loaded faster-whisper model: {model_size} on {device}")
        except ImportError:
            logger.error("faster-whisper not installed. Run: pip install faster-whisper")
            raise
        except Exception as e:
            logger.error(f"Failed to load whisper model: {e}")
            raise

    return _whisper_models[cache_key]


def transcribe_audio_sync(
    audio_path: str,
    model_size: str = "medium",
    language: str | None = None,
    device: str = "auto",
) -> Generator[dict, None, None]:
    """
    Transcribe audio file using faster-whisper.
    Yields segments as they are processed.

    Args:
        audio_path: Path to the audio file
        model_size: Whisper model size (tiny, base, small, medium, large)
        language: Language code (e.g., 'ja', 'en') or None for auto-detection
        device: Device to use ('auto', 'cuda', 'cpu')

    Yields:
        dict with keys: text, start, end, words (optional)
    """
    model = get_whisper_model(model_size, device)

    # Transcribe with word timestamps for better precision
    segments, info = model.transcribe(
        audio_path,
        language=language,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,  # Filter out silence
    )

    logger.info(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")

    for segment in segments:
        yield {
            "text": segment.text.strip(),
            "start": segment.start,
            "end": segment.end,
            "words": [
                {"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
                for w in (segment.words or [])
            ],
        }


async def transcribe_audio(
    audio_path: str,
    model_size: str = "medium",
    language: str | None = None,
    device: str = "auto",
) -> tuple[str, list[dict]]:
    """
    Async wrapper for transcription.

    Returns:
        Tuple of (full_text, segments_list)
    """
    loop = asyncio.get_event_loop()

    def _transcribe():
        segments = []
        full_text = []
        for segment in transcribe_audio_sync(audio_path, model_size, language, device):
            segments.append(segment)
            full_text.append(segment["text"])
        return " ".join(full_text), segments

    return await loop.run_in_executor(None, _transcribe)


async def process_transcription_job(
    db: Session,
    job: TranscriptionJob,
    progress_callback: Optional[Callable] = None,
) -> bool:
    """
    Process a transcription job.

    Args:
        db: Database session
        job: TranscriptionJob to process
        progress_callback: Optional callback for progress updates (percent: float)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Update status to processing
        job.status = TranscriptionStatus.PROCESSING
        job.started_at = datetime.now()
        job.progress_percent = 0.0
        db.commit()

        # Get audio file path
        if not job.audio_file:
            raise ValueError("No audio file associated with job")

        audio_path = job.audio_file.file_path
        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Determine model and device
        model_size = job.model_size or settings.whisper_model_size
        language = job.language or settings.whisper_language  # デフォルト: ja
        device = settings.whisper_device

        logger.info(f"Starting transcription job {job.id}: {audio_path}")

        # Run transcription
        segments = []
        full_text = []
        total_duration = job.audio_file.duration_seconds or 0

        for i, segment in enumerate(transcribe_audio_sync(audio_path, model_size, language, device)):
            segments.append(segment)
            full_text.append(segment["text"])

            # Update progress if we know duration
            if total_duration > 0 and progress_callback:
                progress = min(99.0, (segment["end"] / total_duration) * 100)
                job.progress_percent = progress
                db.commit()
                await asyncio.sleep(0)  # Allow other tasks to run

        # Finalize
        job.result_text = " ".join(full_text)
        job.result_segments = segments
        job.status = TranscriptionStatus.COMPLETED
        job.progress_percent = 100.0
        job.completed_at = datetime.now()
        db.commit()

        logger.info(f"Completed transcription job {job.id}")
        return True

    except Exception as e:
        logger.error(f"Transcription job {job.id} failed: {e}")
        job.status = TranscriptionStatus.FAILED
        job.error_message = str(e)
        job.completed_at = datetime.now()
        db.commit()
        return False


def get_pending_jobs(db: Session, limit: int = 10) -> list[TranscriptionJob]:
    """Get pending transcription jobs ordered by creation time."""
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    stmt = (
        select(TranscriptionJob)
        .options(joinedload(TranscriptionJob.audio_file))
        .where(TranscriptionJob.status == TranscriptionStatus.PENDING)
        .order_by(TranscriptionJob.created_at)
        .limit(limit)
    )
    return list(db.execute(stmt).unique().scalars().all())
