import uuid

from sqlalchemy import select

from app.models import (
    AudioFile,
    AudioSource,
    PromptTemplate,
    Summary,
    TranscriptionEngine,
    TranscriptionJob,
    TranscriptionStatus,
)
from app.services import summarization


def _completed_job(db, user_id: int) -> TranscriptionJob:
    audio_file = AudioFile(
        user_id=user_id,
        source=AudioSource.UPLOAD,
        original_filename="seminar.wav",
        stored_filename="seminar.wav",
        file_path="/tmp/seminar.wav",
        file_size=123,
        mime_type="audio/wav",
    )
    job = TranscriptionJob(
        id=uuid.uuid4(),
        audio_file=audio_file,
        user_id=user_id,
        status=TranscriptionStatus.COMPLETED,
        engine=TranscriptionEngine.PARAKEET_JA,
        model_size="parakeet-tdt_ctc-0.6b-ja",
        result_text="文字起こし結果",
    )
    db.add(audio_file)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_enqueue_auto_llm_jobs_for_configured_template(db, regular_user, monkeypatch):
    monkeypatch.setattr(
        summarization.settings,
        "auto_llm_prompt_template_names",
        "文字起こしの精緻化",
    )
    template = PromptTemplate(
        name=" 文字起こしの精緻化",
        description="文字起こしを読みやすく整える",
        system_prompt="system",
        user_prompt_template="{text}",
        is_active=True,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    job = _completed_job(db, regular_user.id)

    created = summarization.enqueue_auto_llm_jobs_for_transcription(db, job)
    duplicate = summarization.enqueue_auto_llm_jobs_for_transcription(db, job)
    summaries = db.execute(
        select(Summary).where(Summary.transcription_job_id == job.id)
    ).scalars().all()

    assert len(created) == 1
    assert duplicate == []
    assert len(summaries) == 1
    assert summaries[0].prompt_template_id == template.id
