"""Router for managing LLM post-processing jobs."""
import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user, verify_csrf_token
from app.models import PromptTemplate, Summary, SummaryStatus, TranscriptionJob, TranscriptionStatus
from app.models.user import User
from app.schemas.summary import (
    PromptTemplateCreate,
    PromptTemplateResponse,
    PromptTemplateUpdate,
    SummaryCreate,
    SummaryResponse,
)
from app.services import summarization
from app.templating import templates

settings = get_settings()
router = APIRouter(prefix="/summary", tags=["summary"])


def _attachment_headers(filename: str) -> dict[str, str]:
    return {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
    }


@router.get("/templates", response_class=HTMLResponse)
async def prompt_templates_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """List prompt templates."""
    stmt = select(PromptTemplate).order_by(PromptTemplate.name)
    if not current_user.is_admin:
        stmt = stmt.where(PromptTemplate.is_active == True)
    prompt_templates = db.execute(stmt).scalars().all()

    return templates.TemplateResponse(
        "summary/templates.html",
        {
            "request": request,
            "title": "プロンプトテンプレート",
            "current_user": current_user,
            "prompt_templates": prompt_templates,
        },
    )


@router.get("/job/{job_id}", response_class=HTMLResponse)
async def summary_detail_page(
    request: Request,
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Summary detail page."""
    stmt = (
        select(Summary)
        .options(
            joinedload(Summary.transcription_job).joinedload(TranscriptionJob.audio_file),
            joinedload(Summary.prompt_template),
        )
        .where(Summary.id == job_id)
        .where(Summary.user_id == current_user.id)
    )
    summary = db.execute(stmt).unique().scalar_one_or_none()

    if not summary:
        raise HTTPException(status_code=404, detail="LLM処理が見つかりません")

    return templates.TemplateResponse(
        "summary/detail.html",
        {
            "request": request,
            "title": "LLM処理",
            "current_user": current_user,
            "summary": summary,
        },
    )


@router.get("/job/{job_id}/download/{export_format}")
async def download_summary_result(
    job_id: uuid.UUID,
    export_format: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Download a completed LLM processing result as Markdown/text."""
    stmt = (
        select(Summary)
        .options(joinedload(Summary.transcription_job).joinedload(TranscriptionJob.audio_file))
        .where(Summary.id == job_id)
        .where(Summary.user_id == current_user.id)
    )
    summary = db.execute(stmt).unique().scalar_one_or_none()
    if not summary:
        raise HTTPException(status_code=404, detail="LLM処理が見つかりません")
    if summary.status != SummaryStatus.COMPLETED or not summary.result_text:
        raise HTTPException(status_code=400, detail="LLM処理が完了していません")

    source_name = "summary"
    if summary.transcription_job and summary.transcription_job.audio_file:
        source_name = summary.transcription_job.audio_file.original_filename
    stem = source_name.rsplit(".", 1)[0] if "." in source_name else source_name
    stem = "".join(char if char.isalnum() or char in "._-" else "_" for char in stem).strip("._-")
    if not stem:
        stem = "summary"

    if export_format == "md":
        filename = f"{stem}-{str(summary.id)[:8]}-llm.md"
        media_type = "text/markdown; charset=utf-8"
    elif export_format == "txt":
        filename = f"{stem}-{str(summary.id)[:8]}-llm.txt"
        media_type = "text/plain; charset=utf-8"
    else:
        raise HTTPException(status_code=404, detail="未対応のダウンロード形式です")

    return Response(
        content=summary.result_text,
        media_type=media_type,
        headers=_attachment_headers(filename),
    )


# API endpoints
@router.post("/api/create", response_model=SummaryResponse)
async def create_summary(
    data: SummaryCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Create a new LLM processing job for a transcription job."""
    # Verify transcription exists and is completed
    stmt = (
        select(TranscriptionJob)
        .where(TranscriptionJob.id == data.transcription_job_id)
        .where(TranscriptionJob.user_id == current_user.id)
    )
    transcription = db.execute(stmt).scalar_one_or_none()

    if not transcription:
        raise HTTPException(status_code=404, detail="文字起こしジョブが見つかりません")

    if transcription.status != TranscriptionStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="文字起こしが完了していません")

    # Create LLM processing job
    try:
        summary = await summarization.create_summary_for_transcription(
            db,
            transcription,
            prompt_template_id=data.prompt_template_id,
            model_name=data.model_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SummaryResponse.model_validate(summary)


@router.post("/api/transcription/{transcription_id}/summarize")
async def summarize_transcription(
    transcription_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    csrf_token: Annotated[str, Form()] = "",
    prompt_template_id: Annotated[str | None, Form()] = None,
):
    """Create an LLM processing job for a transcription."""
    if not verify_csrf_token(csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRFトークンが無効です")
    # Verify transcription exists and is completed
    stmt = (
        select(TranscriptionJob)
        .where(TranscriptionJob.id == transcription_id)
        .where(TranscriptionJob.user_id == current_user.id)
    )
    transcription = db.execute(stmt).scalar_one_or_none()

    if not transcription:
        raise HTTPException(status_code=404, detail="文字起こしジョブが見つかりません")

    if transcription.status != TranscriptionStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="文字起こしが完了していません")

    try:
        parsed_prompt_template_id = int(prompt_template_id) if prompt_template_id else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="プロンプトテンプレートIDが不正です") from exc

    try:
        summary = await summarization.create_summary_for_transcription(
            db,
            transcription,
            prompt_template_id=parsed_prompt_template_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Redirect to LLM processing result page
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/summary/job/{summary.id}", status_code=303)


@router.get("/api/job/{job_id}", response_model=SummaryResponse)
async def get_summary(
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Get an LLM processing job by ID."""
    stmt = (
        select(Summary)
        .where(Summary.id == job_id)
        .where(Summary.user_id == current_user.id)
    )
    summary = db.execute(stmt).scalar_one_or_none()

    if not summary:
        raise HTTPException(status_code=404, detail="LLM処理が見つかりません")

    return SummaryResponse.model_validate(summary)


@router.get("/api/job/{job_id}/progress", response_class=HTMLResponse)
async def summary_progress_partial(
    request: Request,
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """HTMX partial for LLM processing progress."""
    stmt = (
        select(Summary)
        .where(Summary.id == job_id)
        .where(Summary.user_id == current_user.id)
    )
    summary = db.execute(stmt).scalar_one_or_none()

    if not summary:
        raise HTTPException(status_code=404, detail="LLM処理が見つかりません")

    return templates.TemplateResponse(
        "summary/partials/progress.html",
        {
            "request": request,
            "summary": summary,
        },
    )


# Prompt template management (admin only)
@router.get("/api/templates", response_model=list[PromptTemplateResponse])
async def list_prompt_templates(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    include_inactive: bool = False,
):
    """List all prompt templates."""
    stmt = select(PromptTemplate).order_by(PromptTemplate.name)
    if not include_inactive:
        stmt = stmt.where(PromptTemplate.is_active == True)

    templates_list = db.execute(stmt).scalars().all()
    return [PromptTemplateResponse.model_validate(t) for t in templates_list]


@router.post("/api/templates", response_model=PromptTemplateResponse)
async def create_prompt_template(
    data: PromptTemplateCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Create a new prompt template (admin only)."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")

    template = PromptTemplate(
        name=data.name,
        description=data.description,
        system_prompt=data.system_prompt,
        user_prompt_template=data.user_prompt_template,
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    return PromptTemplateResponse.model_validate(template)


@router.put("/api/templates/{template_id}", response_model=PromptTemplateResponse)
async def update_prompt_template(
    template_id: int,
    data: PromptTemplateUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Update a prompt template (admin only)."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")

    stmt = select(PromptTemplate).where(PromptTemplate.id == template_id)
    template = db.execute(stmt).scalar_one_or_none()

    if not template:
        raise HTTPException(status_code=404, detail="テンプレートが見つかりません")

    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(template, field, value)

    db.commit()
    db.refresh(template)

    return PromptTemplateResponse.model_validate(template)
