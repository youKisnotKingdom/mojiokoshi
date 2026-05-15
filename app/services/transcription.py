"""Transcription service for batch audio transcription."""
import asyncio
from datetime import timedelta
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Callable, Generator, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    SpeakerDiarizationStatus,
    TranscriptionEngine,
    TranscriptionJob,
    TranscriptionStatus,
)
import app.services.speaker_diarization as speaker_diarization_service
from app.time_utils import utc_now

settings = get_settings()
logger = logging.getLogger(__name__)

# Lazy-loaded model cache
_whisper_models: dict[str, object] = {}
_parakeet_models: dict[str, object] = {}
_reazon_nemo_models: dict[str, object] = {}
_cohere_transcribe_models: dict[str, tuple[object, object]] = {}

PARAKEET_JA_REPO_ID = "nvidia/parakeet-tdt_ctc-0.6b-ja"
REAZON_NEMO_V2_REPO_ID = "reazon-research/reazonspeech-nemo-v2"
COHERE_TRANSCRIBE_REPO_ID = "CohereLabs/cohere-transcribe-03-2026"
FASTER_WHISPER_PREPROCESS_SAMPLE_RATE = 16000
AUDIO_PREPROCESSING_FILTERS: dict[str, list[str]] = {
    "off": [],
    "light": [
        "highpass=f=80",
        "lowpass=f=7600",
        "dynaudnorm=f=250:g=8:p=0.95",
    ],
    "denoise": [
        "highpass=f=80",
        "lowpass=f=7600",
        "afftdn=nf=-25",
        "dynaudnorm=f=250:g=8:p=0.95",
    ],
}


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

        map_location = "cuda" if runtime_device.startswith("cuda") else "cpu"
        model = nemo_asr.models.ASRModel.from_pretrained(
            model_name=PARAKEET_JA_REPO_ID,
            map_location=map_location,
        )
        if runtime_device.startswith("cuda"):
            model = model.cuda()
        model.eval()
        _parakeet_models[cache_key] = model
        logger.info("Loaded Parakeet JA model on %s", runtime_device)

    return _parakeet_models[cache_key]


def resolve_cached_model_source(repo_id: str) -> str:
    if "/" not in repo_id:
        return repo_id

    cache_roots: list[Path] = []
    for env_name in ("HF_HOME", "TRANSFORMERS_CACHE"):
        env_value = os.environ.get(env_name)
        if not env_value:
            continue
        env_path = Path(env_value).expanduser()
        cache_roots.extend([env_path, env_path / "hub"])

    default_cache_root = Path.home() / ".cache" / "huggingface"
    cache_roots.extend([default_cache_root, default_cache_root / "hub"])

    repo_cache_dir_name = f"models--{repo_id.replace('/', '--')}"
    seen: set[Path] = set()
    for root in cache_roots:
        if root in seen:
            continue
        seen.add(root)
        snapshots_dir = root / repo_cache_dir_name / "snapshots"
        if not snapshots_dir.exists():
            continue

        snapshots = sorted(
            (path for path in snapshots_dir.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for snapshot in snapshots:
            if list(snapshot.glob("*.nemo")):
                return str(snapshot)
            if any(
                (snapshot / marker).exists()
                for marker in (
                    "config.json",
                    "tokenizer_config.json",
                    "processor_config.json",
                    "preprocessor_config.json",
                    "model.safetensors",
                )
            ):
                return str(snapshot)

    return repo_id


def _huggingface_token() -> str | None:
    return (
        os.environ.get("HF_TOKEN")
        or settings.huggingface_token
        or os.environ.get("HUGGINGFACE_TOKEN")
        or None
    )


def get_reazon_nemo_model(device: str = "auto"):
    """Get or create a cached ReazonSpeech NeMo v2 model instance."""
    runtime_device = resolve_runtime_device(device)
    cache_key = f"{REAZON_NEMO_V2_REPO_ID}_{runtime_device}"
    if cache_key not in _reazon_nemo_models:
        try:
            from nemo.collections.asr.models import EncDecRNNTBPEModel
        except ImportError:
            logger.error("nemo_toolkit[asr] not installed. Reazon NeMo v2 cannot be loaded.")
            raise

        model_source = Path(resolve_cached_model_source(REAZON_NEMO_V2_REPO_ID))
        checkpoint_path = model_source
        if model_source.is_dir():
            nemo_files = sorted(model_source.glob("*.nemo"))
            if not nemo_files:
                raise FileNotFoundError(f"Reazon NeMo v2 checkpoint not found: {model_source}")
            checkpoint_path = nemo_files[0]

        map_location = "cuda" if runtime_device.startswith("cuda") else "cpu"
        model = EncDecRNNTBPEModel.restore_from(str(checkpoint_path), map_location=map_location)
        if runtime_device.startswith("cuda"):
            model = model.cuda()
        model.eval()
        _reazon_nemo_models[cache_key] = model
        logger.info("Loaded Reazon NeMo v2 model on %s", runtime_device)

    return _reazon_nemo_models[cache_key]


def get_cohere_transcribe_model(device: str = "auto") -> tuple[object, object]:
    """Get or create a cached Cohere Transcribe processor/model pair."""
    runtime_device = resolve_runtime_device(device)
    cache_key = f"{COHERE_TRANSCRIBE_REPO_ID}_{runtime_device}"
    if cache_key not in _cohere_transcribe_models:
        try:
            import torch
            from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
        except ImportError:
            logger.error("transformers / torch not installed. Cohere Transcribe cannot be loaded.")
            raise

        model_source = resolve_cached_model_source(COHERE_TRANSCRIBE_REPO_ID)
        token = _huggingface_token()
        torch_dtype = torch.bfloat16 if runtime_device.startswith("cuda") else torch.float32
        processor = AutoProcessor.from_pretrained(
            model_source,
            trust_remote_code=True,
            token=token,
        )
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_source,
            trust_remote_code=True,
            torch_dtype=torch_dtype,
            token=token,
        ).to(runtime_device)
        model.eval()
        _cohere_transcribe_models[cache_key] = (processor, model)
        logger.info("Loaded Cohere Transcribe model on %s", runtime_device)

    return _cohere_transcribe_models[cache_key]


def model_size_for_engine(engine: TranscriptionEngine, fallback_model_size: str) -> str:
    if engine == TranscriptionEngine.PARAKEET_JA:
        return "parakeet-tdt_ctc-0.6b-ja"
    if engine == TranscriptionEngine.REAZON_NEMO_V2:
        return "reazonspeech-nemo-v2"
    if engine == TranscriptionEngine.COHERE_TRANSCRIBE:
        return "cohere-transcribe-03-2026"
    return fallback_model_size


def device_for_engine(engine: TranscriptionEngine, fallback_device: str | None = None) -> str:
    if engine == TranscriptionEngine.COHERE_TRANSCRIBE:
        return settings.cohere_transcribe_device or fallback_device or settings.whisper_device
    return fallback_device or settings.whisper_device


def _run_media_command(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True)


def _audio_preprocessing_filters() -> list[str]:
    mode = (settings.audio_preprocessing_mode or "off").strip().lower()
    filters = AUDIO_PREPROCESSING_FILTERS.get(mode)
    if filters is None:
        logger.warning("Unknown audio preprocessing mode `%s`; using off", mode)
        return []
    return filters


def _prepare_audio_for_asr(source: Path, output_path: Path, sample_rate: int) -> Path:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-vn",
    ]
    filters = _audio_preprocessing_filters()
    if filters:
        command.extend(["-af", ",".join(filters)])
    command.extend(["-c:a", "pcm_s16le", str(output_path)])
    _run_media_command(command)
    return output_path


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


def _ensure_audio_duration(db: Session, job: TranscriptionJob, audio_path: Path) -> float:
    """Ensure uploaded files also get duration metadata for progress updates."""
    if job.audio_file and job.audio_file.duration_seconds:
        return float(job.audio_file.duration_seconds)

    try:
        duration = _ffprobe_duration(audio_path)
    except Exception as exc:
        logger.warning("Failed to probe audio duration for job %s: %s", job.id, exc)
        return 0.0

    if job.audio_file:
        job.audio_file.duration_seconds = duration
    job.progress_percent = max(float(job.progress_percent or 0.0), 1.0)
    db.commit()
    return duration


def _normalize_audio_for_parakeet(source: Path, output_path: Path) -> Path:
    return _prepare_audio_for_asr(source, output_path, settings.parakeet_sample_rate)


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


def _parakeet_timestamp_text(entry: dict) -> str:
    if "word" in entry:
        return str(entry.get("word", ""))
    value = entry.get("char", "")
    if isinstance(value, list):
        return "".join(str(item) for item in value)
    return str(value)


def _parakeet_timestamp_units(entries: list[dict], chunk_offset: float) -> list[dict]:
    units = []
    for entry in entries:
        text = _parakeet_timestamp_text(entry)
        if not text:
            continue
        units.append(
            {
                "word": text,
                "start": chunk_offset + float(entry.get("start", 0.0) or 0.0),
                "end": chunk_offset + float(entry.get("end", 0.0) or 0.0),
            }
        )
    return units


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
    source_path = Path(audio_path)

    def _yield_segments(input_path: str) -> Generator[dict, None, None]:
        segments, info = model.transcribe(
            input_path,
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

    if _audio_preprocessing_filters():
        with tempfile.TemporaryDirectory(prefix="asr-preprocess-") as temp_dir_str:
            prepared_path = Path(temp_dir_str) / "preprocessed.wav"
            _prepare_audio_for_asr(
                source_path,
                prepared_path,
                FASTER_WHISPER_PREPROCESS_SAMPLE_RATE,
            )
            yield from _yield_segments(str(prepared_path))
        return

    yield from _yield_segments(audio_path)


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
        for chunk_index, chunk_path in enumerate(chunks):
            result = model.transcribe(
                [str(chunk_path)],
                batch_size=1,
                return_hypotheses=True,
                timestamps=True,
                verbose=False,
            )
            item = result[0]
            chunk_duration = _ffprobe_duration(chunk_path)
            chunk_start = chunk_offset
            chunk_end = chunk_offset + chunk_duration
            timestamps = getattr(item, "timestamp", None) or getattr(item, "timestep", None) or {}
            words = timestamps.get("word") or []
            chars = timestamps.get("char") or []
            timestamp_units = words if len(words) > 1 else chars
            segment_entries = timestamps.get("segment") or []

            if segment_entries:
                for segment in segment_entries:
                    text = str(segment.get("segment", "")).strip()
                    if not text:
                        continue

                    segment_start = chunk_offset + float(segment.get("start", 0.0) or 0.0)
                    segment_end = chunk_offset + float(segment.get("end", 0.0) or 0.0)
                    segment_words = []
                    for unit in timestamp_units:
                        unit_text = _parakeet_timestamp_text(unit)
                        if not unit_text:
                            continue
                        word_start = chunk_offset + float(unit.get("start", 0.0) or 0.0)
                        word_end = chunk_offset + float(unit.get("end", 0.0) or 0.0)
                        if word_end > segment_start and word_start < segment_end:
                            segment_words.append(
                                {
                                    "word": unit_text,
                                    "start": word_start,
                                    "end": word_end,
                                }
                            )

                    yield {
                        "text": text,
                        "start": segment_start,
                        "end": segment_end,
                        "chunk_index": chunk_index,
                        "chunk_start": chunk_start,
                        "chunk_end": chunk_end,
                        "words": segment_words,
                        "language": language,
                    }
            else:
                text = getattr(item, "text", str(item)).strip()
                yield {
                    "text": text,
                    "start": chunk_start,
                    "end": chunk_end,
                    "chunk_index": chunk_index,
                    "chunk_start": chunk_start,
                    "chunk_end": chunk_end,
                    "words": _parakeet_timestamp_units(timestamp_units, chunk_offset),
                    "language": language,
                }
            chunk_offset += chunk_duration


def transcribe_audio_reazon_nemo_sync(
    audio_path: str,
    language: str | None = None,
    device: str = "auto",
) -> Generator[dict, None, None]:
    """Transcribe audio file using ReazonSpeech NeMo v2."""
    runtime_device = resolve_runtime_device(device)
    model = get_reazon_nemo_model(runtime_device)
    source_path = Path(audio_path)
    with tempfile.TemporaryDirectory(prefix="reazon-nemo-job-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        normalized_path = temp_dir / "normalized.wav"
        chunks_dir = temp_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        _prepare_audio_for_asr(source_path, normalized_path, 16000)
        chunks = _split_audio_for_parakeet(normalized_path, chunks_dir)

        chunk_offset = 0.0
        for chunk_index, chunk_path in enumerate(chunks):
            result = model.transcribe([str(chunk_path)], batch_size=1)
            item = result[0]
            text = getattr(item, "text", str(item)).strip()
            chunk_duration = _ffprobe_duration(chunk_path)
            chunk_start = chunk_offset
            chunk_end = chunk_offset + chunk_duration
            if text:
                yield {
                    "text": text,
                    "start": chunk_start,
                    "end": chunk_end,
                    "chunk_index": chunk_index,
                    "chunk_start": chunk_start,
                    "chunk_end": chunk_end,
                    "words": [],
                    "language": language,
                }
            chunk_offset += chunk_duration


def transcribe_audio_cohere_sync(
    audio_path: str,
    language: str | None = None,
    device: str = "auto",
) -> Generator[dict, None, None]:
    """Transcribe audio file using Cohere Transcribe."""
    runtime_device = resolve_runtime_device(device)
    processor, model = get_cohere_transcribe_model(runtime_device)
    source_path = Path(audio_path)
    cohere_language = language or settings.whisper_language or "ja"
    with tempfile.TemporaryDirectory(prefix="cohere-transcribe-job-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        normalized_path = temp_dir / "normalized.wav"
        chunks_dir = temp_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        _prepare_audio_for_asr(source_path, normalized_path, 16000)
        chunks = _split_audio_for_parakeet(normalized_path, chunks_dir)

        chunk_offset = 0.0
        for chunk_index, chunk_path in enumerate(chunks):
            texts = model.transcribe(
                processor=processor,
                audio_files=[str(chunk_path)],
                language=cohere_language,
            )
            text = str(texts[0] if texts else "").strip()
            chunk_duration = _ffprobe_duration(chunk_path)
            chunk_start = chunk_offset
            chunk_end = chunk_offset + chunk_duration
            if text:
                yield {
                    "text": text,
                    "start": chunk_start,
                    "end": chunk_end,
                    "chunk_index": chunk_index,
                    "chunk_start": chunk_start,
                    "chunk_end": chunk_end,
                    "words": [],
                    "language": cohere_language,
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

    if engine == TranscriptionEngine.REAZON_NEMO_V2:
        yield from transcribe_audio_reazon_nemo_sync(audio_path, language=language, device=device)
        return

    if engine == TranscriptionEngine.COHERE_TRANSCRIBE:
        yield from transcribe_audio_cohere_sync(audio_path, language=language, device=device)
        return

    if engine in (TranscriptionEngine.FASTER_WHISPER, TranscriptionEngine.WHISPER):
        yield from transcribe_audio_sync(audio_path, model_size=model_size, language=language, device=device)
        return

    raise ValueError(
        f"Engine `{engine.value}` is not supported by the production worker. "
        "Use Parakeet JA, Reazon NeMo v2, Cohere Transcribe, or Faster Whisper."
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
        language = job.language
        device = device_for_engine(job.engine, settings.whisper_device)

        logger.info(
            "Starting transcription job %s: %s (engine=%s, device=%s)",
            job.id,
            audio_path,
            job.engine.value,
            device,
        )

        segments = []
        full_text = []
        total_duration = _ensure_audio_duration(db, job, Path(audio_path))
        current_chunk_index: int | None = None
        current_chunk_segments: list[dict] = []

        def _segment_chunk_index(segment: dict, fallback_index: int) -> int:
            if segment.get("chunk_index") is not None:
                return int(segment["chunk_index"])
            chunk_seconds = max(1, int(settings.parakeet_chunk_seconds or 300))
            try:
                return int(float(segment.get("start", 0.0) or 0.0) // chunk_seconds)
            except (TypeError, ValueError):
                return fallback_index

        def _save_current_chunk(chunk_index: int | None, chunk_segments: list[dict]) -> None:
            if chunk_index is None or not chunk_segments:
                return
            from app.services import summarization

            raw_text = " ".join(
                str(segment.get("text", "")).strip()
                for segment in chunk_segments
                if str(segment.get("text", "")).strip()
            ).strip()
            if not raw_text:
                return

            start_values = [
                float(segment.get("chunk_start", segment.get("start", 0.0)) or 0.0)
                for segment in chunk_segments
            ]
            end_values = [
                float(segment.get("chunk_end", segment.get("end", 0.0)) or 0.0)
                for segment in chunk_segments
            ]
            summarization.create_or_update_transcription_chunk(
                db,
                job,
                chunk_index=chunk_index,
                start_seconds=min(start_values) if start_values else 0.0,
                end_seconds=max(end_values) if end_values else 0.0,
                raw_text=raw_text,
                raw_segments=chunk_segments,
            )

        for segment_index, segment in enumerate(
            transcribe_batch_job_sync(job.engine, audio_path, model_size, language, device)
        ):
            segment_chunk_index = _segment_chunk_index(segment, segment_index)
            if current_chunk_index is None:
                current_chunk_index = segment_chunk_index
            elif segment_chunk_index != current_chunk_index:
                _save_current_chunk(current_chunk_index, current_chunk_segments)
                current_chunk_segments = []
                current_chunk_index = segment_chunk_index

            segments.append(segment)
            current_chunk_segments.append(segment)
            full_text.append(segment["text"])

            if total_duration > 0:
                segment_end = segment.get("end")
                if segment_end is None:
                    progress = 99.0
                else:
                    progress = min(99.0, (segment_end / total_duration) * 100)
                job.progress_percent = progress
                db.commit()
                if progress_callback:
                    progress_callback(job)
                await asyncio.sleep(0)

        _save_current_chunk(current_chunk_index, current_chunk_segments)

        job.result_text = " ".join(full_text)
        job.result_segments = segments
        job.status = TranscriptionStatus.COMPLETED
        job.progress_percent = 100.0
        job.completed_at = utc_now()
        if settings.enable_speaker_diarization and job.enable_speaker_diarization:
            job.speaker_diarization_status = SpeakerDiarizationStatus.PENDING
            job.speaker_diarization_error = None
            job.speaker_diarization_started_at = None
            job.speaker_diarization_completed_at = None
        else:
            job.speaker_diarization_status = SpeakerDiarizationStatus.NOT_REQUESTED
        db.commit()

        try:
            from app.services import summarization

            summarization.enqueue_auto_llm_jobs_for_transcription(db, job)
        except Exception as exc:
            logger.warning("Automatic LLM processing enqueue failed for job %s: %s", job.id, exc)

        logger.info(f"Completed transcription job {job.id}")
        return True

    except Exception as e:
        logger.error(f"Transcription job {job.id} failed: {e}")
        job.status = TranscriptionStatus.FAILED
        job.error_message = str(e)
        job.completed_at = utc_now()
        db.commit()
        return False


def claim_pending_speaker_diarization_jobs(db: Session, limit: int = 1) -> list[uuid.UUID]:
    """Claim completed transcription jobs that still need speaker diarization."""
    from sqlalchemy import select

    stmt = (
        select(TranscriptionJob)
        .where(TranscriptionJob.status == TranscriptionStatus.COMPLETED)
        .where(TranscriptionJob.enable_speaker_diarization.is_(True))
        .where(TranscriptionJob.speaker_diarization_status == SpeakerDiarizationStatus.PENDING)
        .where(TranscriptionJob.result_text.is_not(None))
        .order_by(TranscriptionJob.completed_at, TranscriptionJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    jobs = list(db.execute(stmt).scalars().all())
    if not jobs:
        return []

    now = utc_now()
    claimed_ids: list[uuid.UUID] = []
    for job in jobs:
        job.speaker_diarization_status = SpeakerDiarizationStatus.PROCESSING
        job.speaker_diarization_started_at = now
        job.speaker_diarization_completed_at = None
        job.speaker_diarization_error = None
        claimed_ids.append(job.id)

    db.commit()
    return claimed_ids


def requeue_stale_speaker_diarization_jobs(db: Session, stale_after_seconds: int) -> list[uuid.UUID]:
    """Return long-stuck speaker diarization jobs back to pending."""
    if stale_after_seconds <= 0:
        return []

    from sqlalchemy import select

    cutoff = utc_now() - timedelta(seconds=stale_after_seconds)
    stmt = (
        select(TranscriptionJob)
        .where(TranscriptionJob.speaker_diarization_status == SpeakerDiarizationStatus.PROCESSING)
        .where(TranscriptionJob.speaker_diarization_started_at.is_not(None))
        .where(TranscriptionJob.speaker_diarization_started_at < cutoff)
        .with_for_update(skip_locked=True)
    )
    jobs = list(db.execute(stmt).scalars().all())
    if not jobs:
        return []

    now = utc_now()
    recovered_ids: list[uuid.UUID] = []
    for job in jobs:
        job.speaker_diarization_status = SpeakerDiarizationStatus.PENDING
        job.speaker_diarization_started_at = None
        job.speaker_diarization_completed_at = None
        message = (
            f"Recovered from stale speaker diarization state at {now.isoformat()} "
            f"after exceeding {stale_after_seconds}s timeout."
        )
        job.speaker_diarization_error = (
            f"{job.speaker_diarization_error}\n{message}"
            if job.speaker_diarization_error
            else message
        )
        recovered_ids.append(job.id)

    db.commit()
    logger.warning(
        "Re-queued %d stale speaker diarization job(s): %s",
        len(recovered_ids),
        ", ".join(str(job_id) for job_id in recovered_ids),
    )
    return recovered_ids


async def process_speaker_diarization_job_by_id(job_id: uuid.UUID) -> bool:
    """Process a claimed speaker diarization job in its own DB session."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        job = load_job_for_processing(db, job_id)
        if not job:
            logger.error("Claimed speaker diarization job not found: %s", job_id)
            return False
        return await process_speaker_diarization_job(db, job)
    finally:
        db.close()


async def process_speaker_diarization_job(db: Session, job: TranscriptionJob) -> bool:
    """Attach speaker labels to a completed ASR result without blocking ASR completion."""
    try:
        if job.status != TranscriptionStatus.COMPLETED:
            raise ValueError("speaker diarization requires a completed transcription job")
        if not job.enable_speaker_diarization:
            job.speaker_diarization_status = SpeakerDiarizationStatus.NOT_REQUESTED
            job.speaker_diarization_completed_at = utc_now()
            db.commit()
            return True
        if not settings.enable_speaker_diarization:
            raise RuntimeError("speaker diarization is disabled by server configuration")
        if not job.audio_file:
            raise ValueError("No audio file associated with job")

        audio_path = job.audio_file.file_path
        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        if job.speaker_diarization_status != SpeakerDiarizationStatus.PROCESSING:
            job.speaker_diarization_status = SpeakerDiarizationStatus.PROCESSING
            job.speaker_diarization_started_at = utc_now()
            job.speaker_diarization_completed_at = None
            job.speaker_diarization_error = None
            db.commit()

        logger.info("Starting speaker diarization job %s: %s", job.id, audio_path)
        speaker_turns = await asyncio.get_event_loop().run_in_executor(
            None, lambda: speaker_diarization_service.diarize_audio(audio_path)
        )
        segments = job.result_segments if isinstance(job.result_segments, list) else []
        labelled_segments = speaker_diarization_service.assign_speakers_to_segments(
            segments, speaker_turns
        )

        job.result_segments = labelled_segments
        job.speaker_diarization_turns = speaker_turns
        job.speaker_diarization_status = SpeakerDiarizationStatus.COMPLETED
        job.speaker_diarization_completed_at = utc_now()
        job.speaker_diarization_error = None
        db.commit()
        logger.info("Completed speaker diarization job %s", job.id)
        return True

    except Exception as exc:
        logger.error("Speaker diarization job %s failed: %s", job.id, exc)
        job.speaker_diarization_status = SpeakerDiarizationStatus.FAILED
        job.speaker_diarization_error = str(exc)
        job.speaker_diarization_completed_at = utc_now()
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
