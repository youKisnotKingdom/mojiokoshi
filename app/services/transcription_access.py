from app.models import TranscriptionJob
from app.models.user import User


def _is_hidden_job(job: TranscriptionJob) -> bool:
    """Future-facing hook for jobs that should stay out of normal shared access."""
    visibility = getattr(job, "visibility", None)
    if visibility == "confidential":
        return True
    return bool(getattr(job, "is_confidential", False))


def can_view_transcription_job(user: User | None, job: TranscriptionJob | None) -> bool:
    if user is None or job is None or not user.is_active:
        return False
    if user.is_admin or job.user_id == user.id:
        return True
    return not _is_hidden_job(job)


def can_manage_transcription_job(user: User | None, job: TranscriptionJob | None) -> bool:
    if user is None or job is None or not user.is_active:
        return False
    return user.is_admin or job.user_id == user.id
