"""Transcription service for batch audio transcription."""
import asyncio
import logging
import uuid
from pathlib import Path
from typing import Callable, Generator, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import TranscriptionEngine, TranscriptionJob, TranscriptionStatus
from app.time_utils import utc_now

settings = get_settings()
logger = logging.getLogger(__name__)

# Lazy-loaded model cache
_whisper_models: dict[str, object] = {}
_parakeet_models: dict[str, object] = {}

PARAKEET_JA_REPO_ID = "nvidia/parakeet-tdt_ctc-0.6b-ja"


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


def resolve_runtime_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def get_parakeet_model(device: str = "auto"):
    """Get or create a cached Parakeet JA model instance."""
    runtime_device = resolve_runtime_device(device)
    cache_key = f"{PARAKEET_JA_REPO_ID}_{runtime_device}"
    if cache_key not in _parakeet_models:
        try:
            import nemo.collections.asr as nemo_asr
        except ImportError:
            logger.error("nemo_toolkit[asr] not installed. Run: pip install nemo_toolkit[asr]")
            raise

        model = nemo_asr.models.ASRModel.from_pretrained(model_name=PARAKEET_JA_REPO_ID)
        if runtime_device.startswith("cuda"):
            model = model.cuda()
        model.eval()
        _parakeet_models[cache_key] = model
        logger.info("Loaded Parakeet JA model on %s", runtime_device)

    return _parakeet_models[cache_key]


def transcribe_audio_sync(
    audio_path: str,
    model_size: str = "medium",
    language: str | None = None,
    device: str = "auto",
) -> Generator[dict, None, None]:
    """
    Transcribe audio file using faster-whisper.
    Yields segments as they are processed.
    """
    model = get_whisper_model(model_size, device)

    segments, info = model.transcribe(
        audio_path,
        language=language,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
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
    """Async wrapper for transcription."""
    loop = asyncio.get_event_loop()

    def _transcribe():
        segments = []
        full_text = []
        for segment in transcribe_audio_sync(audio_path, model_size, language, device):
            segments.append(segment)
            full_text.append(segment["text"])
        return " ".join(full_text), segments

    return await loop.run_in_executor(None, _transcribe)


def transcribe_audio_parakeet_sync(
    audio_path: str,
    language: str | None = None,
    device: str = "auto",
) -> Generator[dict, None, None]:
    """Transcribe audio file using Parakeet JA."""
    runtime_device = resolve_runtime_device(device)
    model = get_parakeet_model(runtime_device)
    result = model.transcribe([audio_path], batch_size=1)
    item = result[0]
    text = getattr(item, "text", str(item)).strip()
    yield {
        "text": text,
        "start": 0.0,
        "end": None,
        "words": [],
        "language": language,
    }


def transcribe_batch_job_sync(
    engine: TranscriptionEngine,
    audio_path: str,
    model_size: str,
    language: str | None,
    device: str,
) -> Generator[dict, None, None]:
    if engine == TranscriptionEngine.PARAKEET_JA:
        yield from transcribe_audio_parakeet_sync(audio_path, language=language, device=device)
        return

    if engine in (TranscriptionEngine.FASTER_WHISPER, TranscriptionEngine.WHISPER):
        yield from transcribe_audio_sync(audio_path, model_size=model_size, language=language, device=device)
        return

    raise ValueError(
        f"Engine `{engine.value}` is not supported by the production worker. "
        "Use Parakeet JA or Faster Whisper."
    )


def claim_pending_jobs(db: Session, limit: int = 1) -> list[uuid.UUID]:
    """Claim pending transcription jobs safely using row locking."""
    from sqlalchemy import select

    stmt = (
        select(TranscriptionJob)
        .where(TranscriptionJob.status == TranscriptionStatus.PENDING)
        .order_by(TranscriptionJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    jobs = list(db.execute(stmt).scalars().all())
    if not jobs:
        return []

    now = utc_now()
    claimed_ids: list[uuid.UUID] = []
    for job in jobs:
        job.status = TranscriptionStatus.PROCESSING
        job.started_at = now
        job.progress_percent = 0.0
        job.error_message = None
        claimed_ids.append(job.id)

    db.commit()
    return claimed_ids


def load_job_for_processing(db: Session, job_id: uuid.UUID) -> TranscriptionJob | None:
    """Load a claimed transcription job with its audio file."""
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    stmt = (
        select(TranscriptionJob)
        .options(joinedload(TranscriptionJob.audio_file))
        .where(TranscriptionJob.id == job_id)
    )
    return db.execute(stmt).unique().scalar_one_or_none()


async def process_transcription_job_by_id(
    job_id: uuid.UUID,
    progress_callback: Optional[Callable] = None,
) -> bool:
    """Process a claimed transcription job in its own DB session."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        job = load_job_for_processing(db, job_id)
        if not job:
            logger.error("Claimed transcription job not found: %s", job_id)
            return False
        return await process_transcription_job(db, job, progress_callback)
    finally:
        db.close()


async def process_transcription_job(
    db: Session,
    job: TranscriptionJob,
    progress_callback: Optional[Callable] = None,
) -> bool:
    """Process a transcription job."""
    try:
        job.status = TranscriptionStatus.PROCESSING
        if not job.started_at:
            job.started_at = utc_now()
        job.progress_percent = max(job.progress_percent or 0.0, 0.0)
        db.commit()

        if not job.audio_file:
            raise ValueError("No audio file associated with job")

        audio_path = job.audio_file.file_path
        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        model_size = job.model_size or settings.whisper_model_size
        language = job.language or settings.whisper_language
        device = settings.whisper_device

        logger.info(f"Starting transcription job {job.id}: {audio_path}")

        segments = []
        full_text = []
        total_duration = job.audio_file.duration_seconds or 0

        for segment in transcribe_batch_job_sync(job.engine, audio_path, model_size, language, device):
            segments.append(segment)
            full_text.append(segment["text"])

            if total_duration > 0 and progress_callback:
                segment_end = segment.get("end")
                if segment_end is None:
                    progress = 99.0
                else:
                    progress = min(99.0, (segment_end / total_duration) * 100)
                job.progress_percent = progress
                db.commit()
                await asyncio.sleep(0)

        job.result_text = " ".join(full_text)
        job.result_segments = segments
        job.status = TranscriptionStatus.COMPLETED
        job.progress_percent = 100.0
        job.completed_at = utc_now()
        db.commit()

        logger.info(f"Completed transcription job {job.id}")
        return True

    except Exception as e:
        logger.error(f"Transcription job {job.id} failed: {e}")
        job.status = TranscriptionStatus.FAILED
        job.error_message = str(e)
        job.completed_at = utc_now()
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
