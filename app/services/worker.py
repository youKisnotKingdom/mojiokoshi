"""
Background worker for processing transcription and summarization jobs.
"""
import asyncio
import logging
import signal

from app.config import get_settings
from app.database import SessionLocal
from app.services import cleanup, summarization, transcription

settings = get_settings()
logger = logging.getLogger(__name__)

_running = False
_cleanup_counter = 0
CLEANUP_INTERVAL = 720
MAX_RETRIES = 3


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


async def worker_loop(poll_interval: float | None = None):
    """Main worker loop that processes jobs continuously."""
    global _running, _cleanup_counter
    _running = True
    _cleanup_counter = 0

    poll_interval = poll_interval or settings.worker_poll_interval
    transcription_concurrency = max(1, settings.worker_transcription_concurrency)
    summary_concurrency = max(1, settings.worker_summary_concurrency)

    logger.info(
        "Worker started (poll_interval=%.1fs, transcription_concurrency=%d, summary_concurrency=%d)",
        poll_interval,
        transcription_concurrency,
        summary_concurrency,
    )

    while _running:
        try:
            transcription_count = await process_transcription_jobs(poll_interval, transcription_concurrency)
            summary_count = await process_summary_jobs(poll_interval, summary_concurrency)

            _cleanup_counter += 1
            if _cleanup_counter >= CLEANUP_INTERVAL:
                _cleanup_counter = 0
                await cleanup.run_cleanup_job()

            if transcription_count == 0 and summary_count == 0:
                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            logger.info("Worker cancelled")
            break
        except Exception as e:
            logger.error("Worker error: %s", e)
            await asyncio.sleep(poll_interval)

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
