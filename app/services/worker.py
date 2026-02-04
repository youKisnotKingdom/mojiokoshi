"""
Background worker for processing transcription and summarization jobs.
"""
import asyncio
import logging
import signal
import sys

from app.config import get_settings
from app.database import SessionLocal
from app.services import summarization, transcription

settings = get_settings()
logger = logging.getLogger(__name__)

# Worker state
_running = False


async def process_transcription_jobs():
    """Process pending transcription jobs."""
    db = SessionLocal()
    try:
        jobs = transcription.get_pending_jobs(db, limit=1)
        for job in jobs:
            logger.info(f"Processing transcription job: {job.id}")
            await transcription.process_transcription_job(db, job)
    except Exception as e:
        logger.error(f"Error processing transcription jobs: {e}")
    finally:
        db.close()


async def process_summary_jobs():
    """Process pending summary jobs."""
    db = SessionLocal()
    try:
        summaries = summarization.get_pending_summaries(db, limit=1)
        for summary in summaries:
            logger.info(f"Processing summary: {summary.id}")
            await summarization.process_summary(db, summary)
    except Exception as e:
        logger.error(f"Error processing summary jobs: {e}")
    finally:
        db.close()


async def worker_loop(poll_interval: float = 5.0):
    """
    Main worker loop that processes jobs continuously.

    Args:
        poll_interval: Seconds to wait between checks for new jobs
    """
    global _running
    _running = True

    logger.info("Worker started")

    while _running:
        try:
            # Process one transcription job
            await process_transcription_jobs()

            # Process one summary job
            await process_summary_jobs()

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
