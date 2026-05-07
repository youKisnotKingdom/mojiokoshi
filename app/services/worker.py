"""
Background worker for processing transcription and summarization jobs.
"""
import asyncio
import logging
import signal
import time

from app.config import get_settings
from app.database import SessionLocal
from app.services import cleanup, runtime_settings, summarization, transcription

settings = get_settings()
logger = logging.getLogger(__name__)

_running = False
MAX_RETRIES = 3


def _cleanup_due(last_cleanup_at: float | None, interval_seconds: int) -> bool:
    """Return whether periodic audio cleanup should run now."""
    if interval_seconds <= 0:
        return False
    if last_cleanup_at is None:
        return True
    return (time.monotonic() - last_cleanup_at) >= interval_seconds


def _apply_runtime_settings() -> None:
    db = SessionLocal()
    try:
        runtime_settings.apply_runtime_settings(db)
    finally:
        db.close()


async def _with_retry(coro_fn, job_id, job_type: str, poll_interval: float):
    """Run a coroutine with exponential backoff retry on transient errors."""
    import httpx as _httpx

    for attempt in range(MAX_RETRIES):
        try:
            await coro_fn()
            return
        except (_httpx.TimeoutException, _httpx.ConnectError, OSError) as e:
            if attempt == MAX_RETRIES - 1:
                logger.error("%s job %s failed after %d retries: %s", job_type, job_id, MAX_RETRIES, e)
            else:
                wait = poll_interval * (2 ** attempt)
                logger.warning("%s job %s attempt %d failed: %s — retrying in %.1fs", job_type, job_id, attempt + 1, e, wait)
                await asyncio.sleep(wait)
        except Exception as e:
            logger.error("%s job %s failed with unrecoverable error: %s", job_type, job_id, e)
            return


async def process_transcription_jobs(poll_interval: float = 5.0, concurrency: int = 1) -> int:
    """Claim and process pending transcription jobs."""
    db = SessionLocal()
    try:
        transcription.requeue_stale_processing_jobs(
            db, settings.worker_transcription_stale_timeout_seconds
        )
        job_ids = transcription.claim_pending_jobs(db, limit=concurrency)
    except Exception as e:
        logger.error("Error claiming transcription jobs: %s", e)
        return 0
    finally:
        db.close()

    if not job_ids:
        return 0

    async def _run(job_id):
        logger.info("Processing transcription job: %s", job_id)
        await _with_retry(
            lambda: transcription.process_transcription_job_by_id(job_id),
            job_id,
            "transcription",
            poll_interval,
        )

    await asyncio.gather(*[_run(job_id) for job_id in job_ids])
    return len(job_ids)


async def process_summary_jobs(poll_interval: float = 5.0, concurrency: int = 1) -> int:
    """Claim and process pending summary jobs."""
    db = SessionLocal()
    try:
        summarization.requeue_stale_processing_summaries(
            db, settings.worker_summary_stale_timeout_seconds
        )
        summary_ids = summarization.claim_pending_summaries(db, limit=concurrency)
    except Exception as e:
        logger.error("Error claiming summary jobs: %s", e)
        return 0
    finally:
        db.close()

    if not summary_ids:
        return 0

    async def _run(summary_id):
        logger.info("Processing summary: %s", summary_id)
        await _with_retry(
            lambda: summarization.process_summary_by_id(summary_id),
            summary_id,
            "summary",
            poll_interval,
        )

    await asyncio.gather(*[_run(summary_id) for summary_id in summary_ids])
    return len(summary_ids)


async def process_chunk_refinement_jobs(poll_interval: float = 5.0, concurrency: int = 1) -> int:
    """Claim and process pending per-transcription-chunk LLM refinement jobs."""
    db = SessionLocal()
    try:
        summarization.requeue_stale_chunk_refinements(
            db, settings.worker_chunk_refinement_stale_timeout_seconds
        )
        chunk_ids = summarization.claim_pending_chunk_refinements(db, limit=concurrency)
    except Exception as e:
        logger.error("Error claiming chunk refinement jobs: %s", e)
        return 0
    finally:
        db.close()

    if not chunk_ids:
        return 0

    async def _run(chunk_id):
        logger.info("Processing chunk refinement: %s", chunk_id)
        await _with_retry(
            lambda: summarization.process_chunk_refinement_by_id(chunk_id),
            chunk_id,
            "chunk-refinement",
            poll_interval,
        )

    await asyncio.gather(*[_run(chunk_id) for chunk_id in chunk_ids])
    return len(chunk_ids)


async def process_speaker_diarization_jobs(poll_interval: float = 5.0, concurrency: int = 1) -> int:
    """Claim and process pending post-ASR speaker diarization jobs."""
    db = SessionLocal()
    try:
        transcription.requeue_stale_speaker_diarization_jobs(
            db, settings.worker_speaker_diarization_stale_timeout_seconds
        )
        job_ids = transcription.claim_pending_speaker_diarization_jobs(db, limit=concurrency)
    except Exception as e:
        logger.error("Error claiming speaker diarization jobs: %s", e)
        return 0
    finally:
        db.close()

    if not job_ids:
        return 0

    async def _run(job_id):
        logger.info("Processing speaker diarization job: %s", job_id)
        await _with_retry(
            lambda: transcription.process_speaker_diarization_job_by_id(job_id),
            job_id,
            "speaker-diarization",
            poll_interval,
        )

    await asyncio.gather(*[_run(job_id) for job_id in job_ids])
    return len(job_ids)


async def worker_loop(poll_interval: float | None = None):
    """Main worker loop that processes jobs continuously."""
    global _running
    _running = True
    last_cleanup_at: float | None = None

    active_config = None

    while _running:
        try:
            _apply_runtime_settings()
            effective_poll_interval = poll_interval or settings.worker_poll_interval
            transcription_concurrency = max(0, settings.worker_transcription_concurrency)
            chunk_refinement_concurrency = max(0, settings.worker_chunk_refinement_concurrency)
            summary_concurrency = max(0, settings.worker_summary_concurrency)
            speaker_diarization_concurrency = max(0, settings.worker_speaker_diarization_concurrency)
            current_config = (
                effective_poll_interval,
                transcription_concurrency,
                chunk_refinement_concurrency,
                summary_concurrency,
                speaker_diarization_concurrency,
                settings.worker_transcription_stale_timeout_seconds,
                settings.worker_chunk_refinement_stale_timeout_seconds,
                settings.worker_summary_stale_timeout_seconds,
                settings.worker_speaker_diarization_stale_timeout_seconds,
                settings.worker_cleanup_interval_seconds,
            )
            if current_config != active_config:
                active_config = current_config
                logger.info(
                    (
                        "Worker settings active (poll_interval=%.1fs, transcription_concurrency=%d, "
                        "chunk_refinement_concurrency=%d, summary_concurrency=%d, "
                        "speaker_diarization_concurrency=%d, "
                        "transcription_stale_timeout=%ds, chunk_refinement_stale_timeout=%ds, "
                        "summary_stale_timeout=%ds, speaker_diarization_stale_timeout=%ds, "
                        "cleanup_interval=%ds)"
                    ),
                    *current_config,
                )

            transcription_count = (
                await process_transcription_jobs(effective_poll_interval, transcription_concurrency)
                if transcription_concurrency > 0
                else 0
            )
            chunk_refinement_count = (
                await process_chunk_refinement_jobs(effective_poll_interval, chunk_refinement_concurrency)
                if chunk_refinement_concurrency > 0
                else 0
            )
            summary_count = (
                await process_summary_jobs(effective_poll_interval, summary_concurrency)
                if summary_concurrency > 0
                else 0
            )
            speaker_diarization_count = (
                await process_speaker_diarization_jobs(effective_poll_interval, speaker_diarization_concurrency)
                if speaker_diarization_concurrency > 0
                else 0
            )

            if _cleanup_due(last_cleanup_at, settings.worker_cleanup_interval_seconds):
                await cleanup.run_cleanup_job()
                last_cleanup_at = time.monotonic()

            if (
                transcription_count == 0
                and chunk_refinement_count == 0
                and summary_count == 0
                and speaker_diarization_count == 0
            ):
                await asyncio.sleep(effective_poll_interval)

        except asyncio.CancelledError:
            logger.info("Worker cancelled")
            break
        except Exception as e:
            logger.error("Worker error: %s", e)
            await asyncio.sleep(poll_interval or settings.worker_poll_interval)

    logger.info("Worker stopped")


def stop_worker():
    """Signal the worker to stop."""
    global _running
    _running = False


def run_worker():
    """Run the worker (blocking)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    def signal_handler(sig, frame):
        logger.info("Shutdown signal received")
        stop_worker()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    asyncio.run(worker_loop())


if __name__ == "__main__":
    run_worker()
