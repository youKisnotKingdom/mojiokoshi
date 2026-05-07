from datetime import timedelta

from app.models import AudioFile, AudioSource
from app.time_utils import utc_now


def _audio_file(expires_delta: timedelta | None, *, deleted=False) -> AudioFile:
    return AudioFile(
        user_id=1,
        source=AudioSource.UPLOAD,
        original_filename="sample.wav",
        stored_filename="sample.wav",
        file_path="/tmp/sample.wav",
        file_size=1,
        mime_type="audio/wav",
        expires_at=utc_now() + expires_delta if expires_delta is not None else None,
        deleted_at=utc_now() if deleted else None,
    )


def test_retention_days_remaining_rounds_up_partial_days():
    audio_file = _audio_file(timedelta(days=1, seconds=1))

    assert audio_file.retention_days_remaining == 2


def test_retention_days_remaining_returns_zero_for_expired_audio():
    audio_file = _audio_file(timedelta(seconds=-1))

    assert audio_file.retention_days_remaining == 0


def test_retention_days_remaining_hidden_for_deleted_or_no_expiration():
    assert _audio_file(timedelta(days=1), deleted=True).retention_days_remaining is None
    assert _audio_file(None).retention_days_remaining is None
