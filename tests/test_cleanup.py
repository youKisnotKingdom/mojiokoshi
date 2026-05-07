from datetime import timedelta

from app.models import AudioFile, AudioSource
from app.services import cleanup
from app.time_utils import utc_now


def _audio_file(user_id: int, path, *, expires_delta: timedelta) -> AudioFile:
    path.write_bytes(b"audio")
    return AudioFile(
        user_id=user_id,
        source=AudioSource.UPLOAD,
        original_filename=path.name,
        stored_filename=path.name,
        file_path=str(path),
        file_size=path.stat().st_size,
        mime_type="audio/wav",
        expires_at=utc_now() + expires_delta,
    )


def test_cleanup_expired_files_deletes_only_expired_audio(db, regular_user, tmp_path):
    expired_path = tmp_path / "expired.wav"
    active_path = tmp_path / "active.wav"
    expired = _audio_file(
        regular_user.id,
        expired_path,
        expires_delta=timedelta(seconds=-1),
    )
    active = _audio_file(
        regular_user.id,
        active_path,
        expires_delta=timedelta(days=1),
    )
    db.add_all([expired, active])
    db.commit()

    deleted, failed = cleanup.cleanup_expired_files(db)

    assert deleted == 1
    assert failed == 0
    assert not expired_path.exists()
    assert active_path.exists()
    db.refresh(expired)
    db.refresh(active)
    assert expired.deleted_at is not None
    assert active.deleted_at is None
