import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.summary import SummaryStatus


class SummaryCreate(BaseModel):
    transcription_job_id: uuid.UUID
    prompt_template_id: int | None = None
    model_name: str | None = None


class SummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transcription_job_id: uuid.UUID
    user_id: int
    status: SummaryStatus
    result_text: str | None
    error_message: str | None
    model_name: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class PromptTemplateCreate(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str
    user_prompt_template: str


class PromptTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    is_active: bool | None = None


class PromptTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    system_prompt: str
    user_prompt_template: str
    is_active: bool
    created_at: datetime
    updated_at: datetime | None
