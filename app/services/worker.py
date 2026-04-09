"""
Background worker for processing transcription and summarization jobs.
"""
import asyncio
import logging
import signal
import sys

from app.config import get_settings
from app.database import SessionLocal
from app.services import cleanup, summarization, transcription

settings = get_settings()
logger = logging.getLogger(__name__)

# Worker state
_running = False
_cleanup_counter = 0
CLEANUP_INTERVAL = 720  # Run cleanup every 720 polls (~1 hour at 5s interval)


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


async def process_transcription_jobs(poll_interval: float = 5.0):
    """Process pending transcription jobs."""
    db = SessionLocal()
    try:
        jobs = transcription.get_pending_jobs(db, limit=1)
        for job in jobs:
            logger.info("Processing transcription job: %s", job.id)
            await _with_retry(
                lambda: transcription.process_transcription_job(db, job),
                job.id,
                "transcription",
                poll_interval,
            )
    except Exception as e:
        logger.error("Error fetching transcription jobs: %s", e)
    finally:
        db.close()


async def process_summary_jobs(poll_interval: float = 5.0):
    """Process pending summary jobs."""
    db = SessionLocal()
    try:
        summaries = summarization.get_pending_summaries(db, limit=1)
        for summary in summaries:
            logger.info("Processing summary: %s", summary.id)
            await _with_retry(
                lambda: summarization.process_summary(db, summary),
                summary.id,
                "summary",
                poll_interval,
            )
    except Exception as e:
        logger.error("Error fetching summary jobs: %s", e)
    finally:
        db.close()


async def worker_loop(poll_interval: float = 5.0):
    """
    Main worker loop that processes jobs continuously.

    Args:
        poll_interval: Seconds to wait between checks for new jobs
    """
    global _running, _cleanup_counter
    _running = True
    _cleanup_counter = 0

    logger.info("Worker started")

    while _running:
        try:
            # Process one transcription job
            await process_transcription_jobs(poll_interval)

            # Process one summary job
            await process_summary_jobs(poll_interval)

            # Run cleanup periodically
            _cleanup_counter += 1
            if _cleanup_counter >= CLEANUP_INTERVAL:
                _cleanup_counter = 0
                await cleanup.run_cleanup_job()

            # Wait before next poll
            await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            logger.info("Worker cancelled")
            break
        except Exception as e:
            logger.error(f"Worker error: {e}")
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
