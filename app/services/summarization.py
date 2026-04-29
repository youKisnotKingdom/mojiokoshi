"""
Summarization service using OpenAI-compatible LLM API.
"""
from dataclasses import dataclass
from datetime import timedelta
import logging
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models import (
    ChunkRefinementStatus,
    PromptTemplate,
    Summary,
    SummaryStatus,
    TranscriptionChunk,
    TranscriptionJob,
    TranscriptionStatus,
)
from app.services import transcript_output
from app.time_utils import utc_now

settings = get_settings()
logger = logging.getLogger(__name__)

REFINED_TRANSCRIPT_TEMPLATE_NAME = "文字起こし整形"
REFINED_TRANSCRIPT_TEMPLATE_ALIASES = {
    REFINED_TRANSCRIPT_TEMPLATE_NAME,
    "文字起こしの精緻化",
}


@dataclass(frozen=True)
class LLMAPIResult:
    content: str
    model_name: str | None = None
    finish_reason: str | None = None
    usage: dict | None = None

    @property
    def metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {}
        if self.usage is not None:
            metadata["usage"] = self.usage
        if self.finish_reason:
            metadata["finish_reason"] = self.finish_reason
            metadata["truncated"] = self.finish_reason == "length"
        if self.model_name:
            metadata["response_model"] = self.model_name
        return metadata


def _configured_auto_template_names() -> list[str]:
    return [
        name.strip()
        for name in settings.auto_llm_prompt_template_names.split(",")
        if name.strip()
    ]


def template_names_match(configured_name: str, actual_name: str) -> bool:
    configured = configured_name.strip()
    actual = actual_name.strip()
    if configured == actual:
        return True
    return configured in REFINED_TRANSCRIPT_TEMPLATE_ALIASES and actual in REFINED_TRANSCRIPT_TEMPLATE_ALIASES

DEFAULT_SYSTEM_PROMPT = """あなたは日本語の会議・講義・研究打ち合わせの文字起こしを整理するアシスタントです。
文字起こしに含まれる事実だけを使い、推測で内容を補わないでください。
固有名詞や専門用語が曖昧な場合は、断定せず「要確認」として扱ってください。
話者ラベルがある場合は、発言者ごとの役割や発言の流れを必要に応じて反映してください。"""

DEFAULT_USER_PROMPT_TEMPLATE = """以下の文字起こしを、共有しやすい日本語の記録として整理してください。

ファイル名: {filename}
文字起こしエンジン: {engine}
モデル: {model_size}
音声長: {duration}
話者分離: {speaker_diarization}

出力形式:
## 概要
全体像を3-5文でまとめる。

## 重要ポイント
主要トピックを箇条書きで整理する。

## 決定事項
決定されたことがあれば書く。なければ「明確な決定事項は確認できません」と書く。

## ToDo / アクション
担当者、期限、作業内容が読み取れるものだけを書く。不明な場合は「要確認」と明記する。

## 未解決・確認事項
議論中の論点、曖昧な固有名詞、追加確認が必要な点を書く。

文字起こし:

{text}"""

CHUNK_REFINEMENT_SYSTEM_PROMPT = """あなたは日本語の音声認識結果を読みやすく整える専門アシスタントです。
入力されたチャンクの事実だけを使い、内容を追加しないでください。
明らかな誤字、句読点、改行、フィラーの過剰な連続だけを読みやすく整えてください。
固有名詞や専門用語が曖昧な場合は、勝手に確定せず「要確認: 候補」の形で残してください。
出力は整形済み本文だけにしてください。"""

CHUNK_REFINEMENT_USER_PROMPT_TEMPLATE = """以下は長い音声文字起こしの一部です。
前後の文脈が切れている可能性があります。参考文脈は意味のつながりを判断するためだけに使い、対象チャンクに存在しない内容を追加しないでください。

ファイル名: {filename}
チャンク: {chunk_index}
時刻: {start_time} - {end_time}

直前の参考文脈:
{previous_context}

対象チャンクの文字起こし:
{text}

整形方針:
- 日本語として読みやすい句読点、段落に整える。
- 誤字らしい箇所は自然に直す。ただし専門用語や人名は断定しない。
- 「えー」「あの」などのフィラーは意味がない連続だけを減らす。
- 意味を要約せず、発話内容の粒度を保つ。
- 追加説明、見出し、注釈は出力しない。
"""


class _PromptContext(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _render_user_prompt(template: str, context: dict[str, object]) -> str:
    try:
        return template.format_map(_PromptContext(context))
    except Exception as exc:
        raise ValueError(
            "プロンプトテンプレートの変数展開に失敗しました。"
            "JSON例などで波括弧を使う場合は {{ と }} にエスケープしてください。"
        ) from exc


async def call_llm_api(
    prompt: str,
    system_prompt: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    result = await call_llm_api_with_metadata(
        prompt,
        system_prompt=system_prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return result.content


async def call_llm_api_with_metadata(
    prompt: str,
    system_prompt: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> LLMAPIResult:
    api_base = settings.llm_api_base_url
    api_key = settings.llm_api_key
    model_name = model or settings.llm_model_name
    request_temperature = settings.llm_temperature if temperature is None else temperature
    request_max_tokens = settings.llm_max_tokens if max_tokens is None else max_tokens

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
        "temperature": request_temperature,
        "max_tokens": request_max_tokens,
    }

    async with httpx.AsyncClient(timeout=float(settings.llm_timeout)) as client:
        response = await client.post(
            f"{api_base}/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

    choice = data["choices"][0]
    content = choice["message"]["content"]
    return LLMAPIResult(
        content=content,
        model_name=data.get("model") or model_name,
        finish_reason=choice.get("finish_reason"),
        usage=data.get("usage"),
    )


async def summarize_text(
    text: str,
    system_prompt: str | None = None,
    user_prompt_template: str | None = None,
    model: str | None = None,
    prompt_context: dict[str, object] | None = None,
) -> str:
    result = await summarize_text_with_metadata(
        text,
        system_prompt=system_prompt,
        user_prompt_template=user_prompt_template,
        model=model,
        prompt_context=prompt_context,
    )
    return result.content


async def summarize_text_with_metadata(
    text: str,
    system_prompt: str | None = None,
    user_prompt_template: str | None = None,
    model: str | None = None,
    prompt_context: dict[str, object] | None = None,
) -> LLMAPIResult:
    system = system_prompt or DEFAULT_SYSTEM_PROMPT
    template = user_prompt_template or DEFAULT_USER_PROMPT_TEMPLATE
    context = dict(prompt_context or {})
    context["text"] = text
    prompt = _render_user_prompt(template, context)
    return await call_llm_api_with_metadata(prompt, system, model)


def _limit_chars(text: str, max_chars: int, *, keep_tail: bool = False) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[-max_chars:] if keep_tail else text[:max_chars]


def _chunk_time(seconds: float | None) -> str:
    value = max(0.0, float(seconds or 0.0))
    minutes, secs = divmod(int(round(value)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _is_refined_transcript_summary(summary: Summary) -> bool:
    template_name = summary.prompt_template.name.strip() if summary.prompt_template else ""
    return template_name in REFINED_TRANSCRIPT_TEMPLATE_ALIASES


def _assembled_refined_transcript_metadata(job: TranscriptionJob) -> dict[str, object]:
    chunks = list(getattr(job, "chunks", []) or [])
    return {
        "source": "chunk_refinement",
        "finish_reason": "assembled",
        "truncated": False,
        "chunk_count": len(chunks),
        "refined_chunk_count": sum(1 for chunk in chunks if (chunk.refined_text or "").strip()),
        "raw_fallback_chunk_count": sum(
            1 for chunk in chunks if not (chunk.refined_text or "").strip() and (chunk.raw_text or "").strip()
        ),
    }


def create_or_update_transcription_chunk(
    db: Session,
    job: TranscriptionJob,
    *,
    chunk_index: int,
    start_seconds: float,
    end_seconds: float,
    raw_text: str,
    raw_segments: list[dict],
) -> TranscriptionChunk:
    """Persist one ASR chunk and enqueue per-chunk LLM refinement when enabled."""
    existing = db.scalar(
        select(TranscriptionChunk)
        .where(TranscriptionChunk.transcription_job_id == job.id)
        .where(TranscriptionChunk.chunk_index == chunk_index)
        .limit(1)
    )
    raw_text = raw_text.strip()
    refinement_status = (
        ChunkRefinementStatus.PENDING
        if settings.enable_chunk_llm_refinement and raw_text
        else ChunkRefinementStatus.SKIPPED
    )

    if existing:
        raw_changed = existing.raw_text != raw_text or existing.raw_segments != raw_segments
        existing.start_seconds = start_seconds
        existing.end_seconds = end_seconds
        existing.raw_text = raw_text
        existing.raw_segments = raw_segments
        if raw_changed:
            existing.refined_text = None
            existing.error_message = None
            existing.token_usage = None
            existing.refinement_started_at = None
            existing.refinement_completed_at = None
            existing.refinement_status = refinement_status
            existing.model_name = settings.llm_model_name
        db.commit()
        db.refresh(existing)
        return existing

    chunk = TranscriptionChunk(
        transcription_job_id=job.id,
        user_id=job.user_id,
        chunk_index=chunk_index,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        raw_text=raw_text,
        raw_segments=raw_segments,
        refinement_status=refinement_status,
        model_name=settings.llm_model_name,
    )
    db.add(chunk)
    db.commit()
    db.refresh(chunk)
    return chunk


def _previous_chunk_context(db: Session, chunk: TranscriptionChunk) -> str:
    max_chars = settings.llm_chunk_refinement_context_chars
    if max_chars <= 0:
        return "なし"

    previous_chunks = list(
        db.execute(
            select(TranscriptionChunk)
            .where(TranscriptionChunk.transcription_job_id == chunk.transcription_job_id)
            .where(TranscriptionChunk.chunk_index < chunk.chunk_index)
            .order_by(TranscriptionChunk.chunk_index.desc())
            .limit(3)
        )
        .scalars()
        .all()
    )
    previous_chunks.reverse()
    context = "\n\n".join(
        (previous.refined_text or previous.raw_text or "").strip()
        for previous in previous_chunks
        if (previous.refined_text or previous.raw_text or "").strip()
    )
    return _limit_chars(context, max_chars, keep_tail=True) or "なし"


def claim_pending_chunk_refinements(db: Session, limit: int = 1) -> list[uuid.UUID]:
    """Claim pending per-chunk LLM refinement jobs safely."""
    if not settings.enable_chunk_llm_refinement:
        return []

    stmt = (
        select(TranscriptionChunk)
        .join(TranscriptionJob, TranscriptionChunk.transcription_job_id == TranscriptionJob.id)
        .where(TranscriptionChunk.refinement_status == ChunkRefinementStatus.PENDING)
        .where(TranscriptionJob.status.in_([TranscriptionStatus.PROCESSING, TranscriptionStatus.COMPLETED]))
        .order_by(TranscriptionChunk.created_at, TranscriptionChunk.chunk_index)
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    chunks = list(db.execute(stmt).scalars().all())
    if not chunks:
        return []

    now = utc_now()
    claimed_ids: list[uuid.UUID] = []
    for chunk in chunks:
        chunk.refinement_status = ChunkRefinementStatus.PROCESSING
        chunk.refinement_started_at = now
        chunk.error_message = None
        chunk.model_name = settings.llm_model_name
        claimed_ids.append(chunk.id)

    db.commit()
    return claimed_ids


def requeue_stale_chunk_refinements(db: Session, stale_after_seconds: int) -> list[uuid.UUID]:
    """Return long-stuck chunk refinements back to pending."""
    if stale_after_seconds <= 0:
        return []

    cutoff = utc_now() - timedelta(seconds=stale_after_seconds)
    stmt = (
        select(TranscriptionChunk)
        .where(TranscriptionChunk.refinement_status == ChunkRefinementStatus.PROCESSING)
        .where(TranscriptionChunk.refinement_started_at.is_not(None))
        .where(TranscriptionChunk.refinement_started_at < cutoff)
        .with_for_update(skip_locked=True)
    )
    chunks = list(db.execute(stmt).scalars().all())
    if not chunks:
        return []

    now = utc_now()
    recovered_ids: list[uuid.UUID] = []
    for chunk in chunks:
        chunk.refinement_status = ChunkRefinementStatus.PENDING
        chunk.refinement_started_at = None
        chunk.refinement_completed_at = None
        message = (
            f"Recovered from stale chunk refinement at {now.isoformat()} "
            f"after exceeding {stale_after_seconds}s timeout."
        )
        chunk.error_message = f"{chunk.error_message}\n{message}" if chunk.error_message else message
        recovered_ids.append(chunk.id)

    db.commit()
    logger.warning(
        "Re-queued %d stale chunk refinement job(s): %s",
        len(recovered_ids),
        ", ".join(str(chunk_id) for chunk_id in recovered_ids),
    )
    return recovered_ids


def load_chunk_for_refinement(db: Session, chunk_id: uuid.UUID) -> TranscriptionChunk | None:
    stmt = (
        select(TranscriptionChunk)
        .options(joinedload(TranscriptionChunk.transcription_job).joinedload(TranscriptionJob.audio_file))
        .where(TranscriptionChunk.id == chunk_id)
    )
    return db.execute(stmt).unique().scalar_one_or_none()


async def process_chunk_refinement_by_id(chunk_id: uuid.UUID) -> bool:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        chunk = load_chunk_for_refinement(db, chunk_id)
        if not chunk:
            logger.error("Claimed transcription chunk not found: %s", chunk_id)
            return False
        return await process_chunk_refinement(db, chunk)
    finally:
        db.close()


async def process_chunk_refinement(db: Session, chunk: TranscriptionChunk) -> bool:
    """Run LLM refinement for one ASR chunk."""
    try:
        if not settings.enable_chunk_llm_refinement:
            chunk.refinement_status = ChunkRefinementStatus.SKIPPED
            chunk.refinement_completed_at = utc_now()
            db.commit()
            return True

        raw_text = (chunk.raw_text or "").strip()
        if not raw_text:
            chunk.refinement_status = ChunkRefinementStatus.SKIPPED
            chunk.refinement_completed_at = utc_now()
            db.commit()
            return True

        if chunk.refinement_status != ChunkRefinementStatus.PROCESSING:
            chunk.refinement_status = ChunkRefinementStatus.PROCESSING
            chunk.refinement_started_at = utc_now()
            db.commit()

        job = chunk.transcription_job
        audio_file = job.audio_file if job else None
        prompt_context = {
            "filename": audio_file.original_filename if audio_file else "",
            "chunk_index": chunk.chunk_index,
            "start_time": _chunk_time(chunk.start_seconds),
            "end_time": _chunk_time(chunk.end_seconds),
            "previous_context": _previous_chunk_context(db, chunk),
            "text": _limit_chars(raw_text, settings.llm_chunk_refinement_max_input_chars),
        }
        prompt = _render_user_prompt(CHUNK_REFINEMENT_USER_PROMPT_TEMPLATE, prompt_context)
        result = await call_llm_api_with_metadata(
            prompt,
            CHUNK_REFINEMENT_SYSTEM_PROMPT,
            model=chunk.model_name,
            temperature=0.1,
            max_tokens=settings.llm_chunk_refinement_max_output_tokens,
        )

        chunk.refined_text = result.content.strip()
        chunk.token_usage = result.metadata or None
        chunk.refinement_status = ChunkRefinementStatus.COMPLETED
        chunk.refinement_completed_at = utc_now()
        chunk.error_message = None
        db.commit()
        return True

    except Exception as exc:
        logger.error("Chunk refinement %s failed: %s", chunk.id, exc)
        chunk.refinement_status = ChunkRefinementStatus.FAILED
        chunk.error_message = str(exc)
        chunk.refinement_completed_at = utc_now()
        db.commit()
        return False


def claim_pending_summaries(db: Session, limit: int = 1) -> list[uuid.UUID]:
    """Claim pending summaries safely using row locking."""
    blocked_jobs = (
        select(TranscriptionChunk.transcription_job_id)
        .where(
            TranscriptionChunk.refinement_status.in_(
                [ChunkRefinementStatus.PENDING, ChunkRefinementStatus.PROCESSING]
            )
        )
        .distinct()
    )
    stmt = (
        select(Summary)
        .where(Summary.status == SummaryStatus.PENDING)
        .where(Summary.transcription_job_id.not_in(blocked_jobs))
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


def requeue_stale_processing_summaries(db: Session, stale_after_seconds: int) -> list[uuid.UUID]:
    """Return long-stuck processing summaries back to pending."""
    if stale_after_seconds <= 0:
        return []

    cutoff = utc_now() - timedelta(seconds=stale_after_seconds)
    stmt = (
        select(Summary)
        .where(Summary.status == SummaryStatus.PROCESSING)
        .where(Summary.started_at.is_not(None))
        .where(Summary.started_at < cutoff)
        .with_for_update(skip_locked=True)
    )
    summaries = list(db.execute(stmt).scalars().all())
    if not summaries:
        return []

    now = utc_now()
    recovered_ids: list[uuid.UUID] = []
    for summary in summaries:
        summary.status = SummaryStatus.PENDING
        summary.started_at = None
        summary.completed_at = None
        message = (
            f"Recovered from stale processing state at {now.isoformat()} "
            f"after exceeding {stale_after_seconds}s timeout."
        )
        summary.error_message = (
            f"{summary.error_message}\n{message}" if summary.error_message else message
        )
        recovered_ids.append(summary.id)

    db.commit()
    logger.warning(
        "Re-queued %d stale summary job(s): %s",
        len(recovered_ids),
        ", ".join(str(summary_id) for summary_id in recovered_ids),
    )
    return recovered_ids


def load_summary_for_processing(db: Session, summary_id: uuid.UUID) -> Summary | None:
    stmt = (
        select(Summary)
        .options(
            joinedload(Summary.transcription_job).joinedload(TranscriptionJob.audio_file),
            joinedload(Summary.transcription_job).joinedload(TranscriptionJob.chunks),
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

        prompt_context = transcript_output.build_summary_prompt_context(transcription)
        text = str(prompt_context.get("text") or "").strip()
        if not text:
            raise ValueError("No transcription text available")

        if _is_refined_transcript_summary(summary):
            refined_text = transcript_output.build_refined_transcript_text(transcription).strip()
            if refined_text:
                summary.result_text = refined_text
                summary.token_usage = _assembled_refined_transcript_metadata(transcription)
                summary.status = SummaryStatus.COMPLETED
                summary.completed_at = utc_now()
                summary.error_message = None
                db.commit()
                logger.info("Completed refined transcript assembly %s", summary.id)
                return True

        system_prompt = None
        user_prompt_template = None
        if summary.prompt_template:
            system_prompt = summary.prompt_template.system_prompt
            user_prompt_template = summary.prompt_template.user_prompt_template

        logger.info(f"Generating summary for job {summary.id}")
        result = await summarize_text_with_metadata(
            text,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            model=summary.model_name,
            prompt_context=prompt_context,
        )

        summary.result_text = result.content
        summary.token_usage = result.metadata or None
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
    if prompt_template_id is not None:
        template = db.get(PromptTemplate, prompt_template_id)
        if not template or not template.is_active:
            raise ValueError("有効なプロンプトテンプレートが見つかりません")

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


def enqueue_auto_llm_jobs_for_transcription(
    db: Session,
    transcription_job: TranscriptionJob,
) -> list[Summary]:
    """Create configured automatic LLM jobs for a completed transcription."""
    template_names = _configured_auto_template_names()
    if not template_names:
        return []

    active_templates = list(db.execute(
        select(PromptTemplate).where(PromptTemplate.is_active.is_(True))
    ).scalars())

    templates_by_name: dict[str, PromptTemplate] = {}
    for template_name in template_names:
        for template in active_templates:
            if template_names_match(template_name, template.name):
                templates_by_name[template_name] = template
                break

    missing = [name for name in template_names if name not in templates_by_name]
    if missing:
        logger.warning(
            "Auto LLM prompt template(s) not found or inactive: %s",
            ", ".join(missing),
        )

    created: list[Summary] = []
    for template_name in template_names:
        template = templates_by_name.get(template_name)
        if not template:
            continue

        existing = db.scalar(
            select(Summary.id)
            .where(Summary.transcription_job_id == transcription_job.id)
            .where(Summary.prompt_template_id == template.id)
            .limit(1)
        )
        if existing:
            continue

        summary = Summary(
            transcription_job_id=transcription_job.id,
            user_id=transcription_job.user_id,
            prompt_template_id=template.id,
            model_name=settings.llm_model_name,
        )
        db.add(summary)
        created.append(summary)

    if created:
        db.commit()
        for summary in created:
            db.refresh(summary)
        logger.info(
            "Enqueued %d automatic LLM job(s) for transcription %s",
            len(created),
            transcription_job.id,
        )

    return created


def get_pending_summaries(db: Session, limit: int = 10) -> list[Summary]:
    from sqlalchemy.orm import joinedload

    stmt = (
        select(Summary)
        .options(
            joinedload(Summary.transcription_job).joinedload(TranscriptionJob.audio_file),
            joinedload(Summary.prompt_template),
        )
        .where(Summary.status == SummaryStatus.PENDING)
        .order_by(Summary.created_at)
        .limit(limit)
    )
    return list(db.execute(stmt).unique().scalars().all())
