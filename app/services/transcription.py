"""Transcription service for batch audio transcription."""
import asyncio
from datetime import timedelta
import logging
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Callable, Generator, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import TranscriptionEngine, TranscriptionJob, TranscriptionStatus
import app.services.speaker_diarization as speaker_diarization_service
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


def _run_media_command(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True)


def _ffprobe_duration(audio_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def _normalize_audio_for_parakeet(source: Path, output_path: Path) -> Path:
    _run_media_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            str(settings.parakeet_sample_rate),
            "-vn",
            str(output_path),
        ]
    )
    return output_path


def _split_audio_for_parakeet(source: Path, output_dir: Path) -> list[Path]:
    chunk_seconds = settings.parakeet_chunk_seconds
    if chunk_seconds <= 0:
        single_path = output_dir / "chunk_0000.wav"
        shutil.copy2(source, single_path)
        return [single_path]

    pattern = output_dir / "chunk_%04d.wav"
    _run_media_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-f",
            "segment",
            "-segment_time",
            str(chunk_seconds),
            "-c",
            "copy",
            "-reset_timestamps",
            "1",
            str(pattern),
        ]
    )
    chunks = sorted(output_dir.glob("chunk_*.wav"))
    if not chunks:
        raise RuntimeError("Parakeet chunking failed: no chunks were created")
    return chunks


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
    source_path = Path(audio_path)
    with tempfile.TemporaryDirectory(prefix="parakeet-job-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        normalized_path = temp_dir / "normalized.wav"
        chunks_dir = temp_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        _normalize_audio_for_parakeet(source_path, normalized_path)
        chunks = _split_audio_for_parakeet(normalized_path, chunks_dir)

        chunk_offset = 0.0
        for chunk_path in chunks:
            result = model.transcribe(
                [str(chunk_path)],
                batch_size=1,
                return_hypotheses=True,
                timestamps=True,
                verbose=False,
            )
            item = result[0]
            chunk_duration = _ffprobe_duration(chunk_path)
            timestamps = getattr(item, "timestamp", None) or getattr(item, "timestep", None) or {}
            words = timestamps.get("word") or []
            segment_entries = timestamps.get("segment") or []

            if segment_entries:
                for segment in segment_entries:
                    text = str(segment.get("segment", "")).strip()
                    if not text:
                        continue

                    segment_start = chunk_offset + float(segment.get("start", 0.0) or 0.0)
                    segment_end = chunk_offset + float(segment.get("end", 0.0) or 0.0)
                    segment_words = []
                    for word in words:
                        word_start = chunk_offset + float(word.get("start", 0.0) or 0.0)
                        word_end = chunk_offset + float(word.get("end", 0.0) or 0.0)
                        if word_end > segment_start and word_start < segment_end:
                            segment_words.append(
                                {
                                    "word": str(word.get("word", "")),
                                    "start": word_start,
                                    "end": word_end,
                                }
                            )

                    yield {
                        "text": text,
                        "start": segment_start,
                        "end": segment_end,
                        "words": segment_words,
                        "language": language,
                    }
            else:
                text = getattr(item, "text", str(item)).strip()
                yield {
                    "text": text,
                    "start": chunk_offset,
                    "end": chunk_offset + chunk_duration,
                    "words": [
                        {
                            "word": str(word.get("word", "")),
                            "start": chunk_offset + float(word.get("start", 0.0) or 0.0),
                            "end": chunk_offset + float(word.get("end", 0.0) or 0.0),
                        }
                        for word in words
                    ],
                    "language": language,
                }
            chunk_offset += chunk_duration


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


def requeue_stale_processing_jobs(db: Session, stale_after_seconds: int) -> list[uuid.UUID]:
    """Return long-stuck processing jobs back to pending."""
    if stale_after_seconds <= 0:
        return []

    from sqlalchemy import select

    cutoff = utc_now() - timedelta(seconds=stale_after_seconds)
    stmt = (
        select(TranscriptionJob)
        .where(TranscriptionJob.status == TranscriptionStatus.PROCESSING)
        .where(TranscriptionJob.started_at.is_not(None))
        .where(TranscriptionJob.started_at < cutoff)
        .with_for_update(skip_locked=True)
    )
    jobs = list(db.execute(stmt).scalars().all())
    if not jobs:
        return []

    now = utc_now()
    recovered_ids: list[uuid.UUID] = []
    for job in jobs:
        job.status = TranscriptionStatus.PENDING
        job.started_at = None
        job.completed_at = None
        job.progress_percent = 0.0
        message = (
            f"Recovered from stale processing state at {now.isoformat()} "
            f"after exceeding {stale_after_seconds}s timeout."
        )
        job.error_message = (
            f"{job.error_message}\n{message}" if job.error_message else message
        )
        recovered_ids.append(job.id)

    db.commit()
    logger.warning(
        "Re-queued %d stale transcription job(s): %s",
        len(recovered_ids),
        ", ".join(str(job_id) for job_id in recovered_ids),
    )
    return recovered_ids


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

        if settings.enable_speaker_diarization and job.enable_speaker_diarization:
            try:
                speaker_turns = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: speaker_diarization_service.diarize_audio(audio_path)
                )
                segments = speaker_diarization_service.assign_speakers_to_segments(
                    segments, speaker_turns
                )
            except Exception as exc:
                logger.warning("Speaker diarization failed for job %s: %s", job.id, exc)

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
