"""
Summarization service using OpenAI-compatible LLM API.
"""
import logging
import uuid

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Summary, SummaryStatus, TranscriptionJob
from app.time_utils import utc_now

settings = get_settings()
logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """あなたは文字起こしテキストを要約するアシスタントです。
以下の文字起こしテキストを、重要なポイントを押さえて簡潔に要約してください。
箇条書きで主要なトピックをまとめ、最後に全体の概要を1-2文で記述してください。"""

DEFAULT_USER_PROMPT_TEMPLATE = """以下の文字起こしテキストを要約してください：

{text}"""


async def call_llm_api(
    prompt: str,
    system_prompt: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
) -> str:
    api_base = settings.llm_api_base_url
    api_key = settings.llm_api_key
    model_name = model or settings.llm_model_name

    if not api_base:
        raise ValueError("LLM API base URL not configured")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{api_base}/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

    return data["choices"][0]["message"]["content"]


async def summarize_text(
    text: str,
    system_prompt: str | None = None,
    user_prompt_template: str | None = None,
    model: str | None = None,
) -> str:
    system = system_prompt or DEFAULT_SYSTEM_PROMPT
    template = user_prompt_template or DEFAULT_USER_PROMPT_TEMPLATE
    prompt = template.format(text=text)
    return await call_llm_api(prompt, system, model)


def claim_pending_summaries(db: Session, limit: int = 1) -> list[uuid.UUID]:
    """Claim pending summaries safely using row locking."""
    from sqlalchemy import select

    stmt = (
        select(Summary)
        .where(Summary.status == SummaryStatus.PENDING)
        .order_by(Summary.created_at)
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    summaries = list(db.execute(stmt).scalars().all())
    if not summaries:
        return []

    now = utc_now()
    claimed_ids: list[uuid.UUID] = []
    for summary in summaries:
        summary.status = SummaryStatus.PROCESSING
        summary.started_at = now
        summary.error_message = None
        claimed_ids.append(summary.id)

    db.commit()
    return claimed_ids


def load_summary_for_processing(db: Session, summary_id: uuid.UUID) -> Summary | None:
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    stmt = (
        select(Summary)
        .options(
            joinedload(Summary.transcription_job),
            joinedload(Summary.prompt_template),
        )
        .where(Summary.id == summary_id)
    )
    return db.execute(stmt).unique().scalar_one_or_none()


async def process_summary_by_id(summary_id: uuid.UUID) -> bool:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        summary = load_summary_for_processing(db, summary_id)
        if not summary:
            logger.error("Claimed summary not found: %s", summary_id)
            return False
        return await process_summary(db, summary)
    finally:
        db.close()


async def process_summary(
    db: Session,
    summary: Summary,
) -> bool:
    try:
        summary.status = SummaryStatus.PROCESSING
        if not summary.started_at:
            summary.started_at = utc_now()
        db.commit()

        transcription = summary.transcription_job
        if not transcription or not transcription.result_text:
            raise ValueError("No transcription text available")

        text = transcription.result_text

        system_prompt = None
        user_prompt_template = None
        if summary.prompt_template:
            system_prompt = summary.prompt_template.system_prompt
            user_prompt_template = summary.prompt_template.user_prompt_template

        logger.info(f"Generating summary for job {summary.id}")
        result = await summarize_text(
            text,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            model=summary.model_name,
        )

        summary.result_text = result
        summary.status = SummaryStatus.COMPLETED
        summary.completed_at = utc_now()
        db.commit()

        logger.info(f"Completed summary {summary.id}")
        return True

    except Exception as e:
        logger.error(f"Summary {summary.id} failed: {e}")
        summary.status = SummaryStatus.FAILED
        summary.error_message = str(e)
        summary.completed_at = utc_now()
        db.commit()
        return False


async def create_summary_for_transcription(
    db: Session,
    transcription_job: TranscriptionJob,
    prompt_template_id: int | None = None,
    model_name: str | None = None,
) -> Summary:
    summary = Summary(
        transcription_job_id=transcription_job.id,
        user_id=transcription_job.user_id,
        prompt_template_id=prompt_template_id,
        model_name=model_name or settings.llm_model_name,
    )
    db.add(summary)
    db.commit()
    db.refresh(summary)
    return summary


def get_pending_summaries(db: Session, limit: int = 10) -> list[Summary]:
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    stmt = (
        select(Summary)
        .options(
            joinedload(Summary.transcription_job),
            joinedload(Summary.prompt_template),
        )
        .where(Summary.status == SummaryStatus.PENDING)
        .order_by(Summary.created_at)
        .limit(limit)
    )
    return list(db.execute(stmt).unique().scalars().all())
