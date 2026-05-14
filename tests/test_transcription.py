"""Tests for transcription endpoints."""
import io
import re

from sqlalchemy import select

from app.models import (
    AudioFile,
    AudioSource,
    RecordingSession,
    RecordingStatus,
    Summary,
    SummaryStatus,
    TranscriptionEngine,
    TranscriptionJob,
    TranscriptionStatus,
)


def get_csrf_token(client, url="/transcription/upload"):
    response = client.get(url)
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    return match.group(1) if match else ""


class TestUploadPage:
    def test_transcription_entry_redirects_to_upload(self, user_client):
        response = user_client.get("/transcription", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/transcription/upload"

    def test_upload_page_requires_auth(self, client):
        # Unauthenticated access returns 401 (not a redirect)
        response = client.get("/transcription/upload", follow_redirects=False)
        assert response.status_code == 401

    def test_upload_page_renders_for_auth_user(self, user_client):
        response = user_client.get("/transcription/upload")
        assert response.status_code == 200
        assert "音声アップロード" in response.text

    def test_upload_page_hides_engine_selection_and_defaults_to_japanese(self, user_client):
        response = user_client.get("/transcription/upload")

        assert response.status_code == 200
        assert 'name="engine"' not in response.text
        assert 'name="model_size"' not in response.text
        assert "文字起こしエンジン" not in response.text
        assert "Whisper用モデルサイズ" not in response.text
        assert re.search(r'<option value="ja"[^>]*selected', response.text)
        if "このジョブで話者分離も実行する" not in response.text:
            assert "話者分離は現在無効です" not in response.text
        assert "ホーム" not in response.text

    def test_upload_page_has_csrf_token(self, user_client):
        response = user_client.get("/transcription/upload")
        assert 'name="csrf_token"' in response.text

    def test_upload_page_exposes_max_upload_size_for_client_validation(self, user_client):
        response = user_client.get("/transcription/upload")
        assert 'data-max-upload-size-bytes="' in response.text
        assert 'data-max-upload-size-mb="' in response.text


class TestFileUpload:
    def test_invalid_file_type_rejected(self, user_client):
        csrf = get_csrf_token(user_client)
        response = user_client.post(
            "/transcription/upload",
            data={"csrf_token": csrf},
            files={"file": ("test.txt", io.BytesIO(b"not audio"), "text/plain")},
        )
        assert response.status_code == 400
        assert "無効なファイル形式" in response.text
        assert "音声または動画ファイル" in response.text

    def test_default_upload_uses_reazon_nemo_and_japanese(self, user_client, db):
        csrf = get_csrf_token(user_client)
        response = user_client.post(
            "/transcription/upload",
            data={"csrf_token": csrf},
            files={"file": ("meeting.mp4", io.BytesIO(b"fake video"), "video/mp4")},
        )

        assert response.status_code == 200, response.text
        job = db.execute(select(TranscriptionJob)).scalar_one()
        assert job.engine == TranscriptionEngine.REAZON_NEMO_V2
        assert job.model_size == "reazonspeech-nemo-v2"
        assert job.language == "ja"

    def test_missing_csrf_rejected(self, user_client):
        response = user_client.post(
            "/transcription/upload",
            data={"csrf_token": ""},
            files={"file": ("test.wav", io.BytesIO(b"fake audio"), "audio/wav")},
        )
        assert response.status_code == 403
        assert "CSRFトークンが無効です" in response.text

    def test_ajax_missing_csrf_returns_inline_error_payload(self, user_client):
        response = user_client.post(
            "/transcription/upload",
            data={"csrf_token": ""},
            files={"file": ("test.wav", io.BytesIO(b"fake audio"), "audio/wav")},
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
        )
        assert response.status_code == 403
        assert response.json()["ok"] is False
        assert "CSRFトークンが無効です" in response.json()["error"]

    def test_unauthenticated_upload_rejected(self, client):
        response = client.post(
            "/transcription/upload",
            data={"csrf_token": "any"},
            files={"file": ("test.wav", io.BytesIO(b"fake audio"), "audio/wav")},
            follow_redirects=False,
        )
        assert response.status_code == 401

    def test_posted_engine_is_ignored_and_admin_default_is_used(self, user_client, db):
        csrf = get_csrf_token(user_client)
        response = user_client.post(
            "/transcription/upload",
            data={
                "engine": "faster_whisper",
                "model_size": "large",
                "csrf_token": csrf,
            },
            files={"file": ("meeting.mp4", io.BytesIO(b"fake video"), "video/mp4")},
        )

        assert response.status_code == 200, response.text
        job = db.execute(select(TranscriptionJob)).scalar_one()
        assert job.engine == TranscriptionEngine.REAZON_NEMO_V2
        assert job.model_size == "reazonspeech-nemo-v2"

    def test_upload_uses_parakeet_when_admin_default_is_parakeet(self, user_client, db, monkeypatch):
        from app.routers import transcription as transcription_router

        monkeypatch.setattr(
            transcription_router.settings,
            "default_transcription_engine",
            "parakeet_ja",
        )

        csrf = get_csrf_token(user_client)
        response = user_client.post(
            "/transcription/upload",
            data={"csrf_token": csrf},
            files={"file": ("meeting.mp4", io.BytesIO(b"fake video"), "video/mp4")},
        )

        assert response.status_code == 200, response.text
        job = db.execute(select(TranscriptionJob)).scalar_one()
        assert job.engine == TranscriptionEngine.PARAKEET_JA
        assert job.model_size == "parakeet-tdt_ctc-0.6b-ja"

    def test_upload_uses_cohere_when_admin_default_is_cohere(self, user_client, db, monkeypatch):
        from app.routers import transcription as transcription_router

        monkeypatch.setattr(
            transcription_router.settings,
            "default_transcription_engine",
            "cohere_transcribe",
        )

        csrf = get_csrf_token(user_client)
        response = user_client.post(
            "/transcription/upload",
            data={"csrf_token": csrf},
            files={"file": ("meeting.mp4", io.BytesIO(b"fake video"), "video/mp4")},
        )

        assert response.status_code == 200, response.text
        job = db.execute(select(TranscriptionJob)).scalar_one()
        assert job.engine == TranscriptionEngine.COHERE_TRANSCRIBE
        assert job.model_size == "cohere-transcribe-03-2026"


class TestDeleteJob:
    def test_delete_job_removes_audio_file_and_related_rows(self, user_client, db, regular_user, tmp_path):
        audio_path = tmp_path / "meeting.wav"
        audio_path.write_bytes(b"audio")
        audio_file = AudioFile(
            user_id=regular_user.id,
            source=AudioSource.UPLOAD,
            original_filename="meeting.wav",
            stored_filename="meeting.wav",
            file_path=str(audio_path),
            file_size=audio_path.stat().st_size,
            mime_type="audio/wav",
        )
        job = TranscriptionJob(
            audio_file=audio_file,
            user_id=regular_user.id,
            status=TranscriptionStatus.COMPLETED,
            engine=TranscriptionEngine.PARAKEET_JA,
            model_size="parakeet-tdt_ctc-0.6b-ja",
            result_text="文字起こし",
        )
        summary = Summary(
            transcription_job=job,
            user_id=regular_user.id,
            status=SummaryStatus.COMPLETED,
            result_text="要約",
            model_name="test-model",
        )
        db.add_all([audio_file, job, summary])
        db.commit()
        audio_id = audio_file.id
        job_id = job.id
        summary_id = summary.id

        csrf = get_csrf_token(user_client)
        response = user_client.post(
            f"/transcription/job/{job_id}/delete",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert not audio_path.exists()
        assert db.get(AudioFile, audio_id) is None
        assert db.get(TranscriptionJob, job_id) is None
        assert db.get(Summary, summary_id) is None

    def test_delete_recording_job_removes_recording_session_reference(self, user_client, db, regular_user, tmp_path):
        audio_path = tmp_path / "recording.webm"
        audio_path.write_bytes(b"audio")
        audio_file = AudioFile(
            user_id=regular_user.id,
            source=AudioSource.RECORDING,
            original_filename="recording.webm",
            stored_filename="recording.webm",
            file_path=str(audio_path),
            file_size=audio_path.stat().st_size,
            mime_type="audio/webm",
        )
        job = TranscriptionJob(
            audio_file=audio_file,
            user_id=regular_user.id,
            status=TranscriptionStatus.COMPLETED,
            engine=TranscriptionEngine.PARAKEET_JA,
            model_size="parakeet-tdt_ctc-0.6b-ja",
            result_text="録音文字起こし",
        )
        session = RecordingSession(
            user_id=regular_user.id,
            status=RecordingStatus.COMPLETED,
            audio_file=audio_file,
        )
        db.add_all([audio_file, job, session])
        db.commit()
        audio_id = audio_file.id
        job_id = job.id
        session_id = session.id

        csrf = get_csrf_token(user_client)
        response = user_client.post(
            f"/transcription/job/{job_id}/delete",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert not audio_path.exists()
        assert db.get(AudioFile, audio_id) is None
        assert db.get(TranscriptionJob, job_id) is None
        assert db.get(RecordingSession, session_id) is None


class TestRecordPage:
    def test_record_page_requires_auth(self, client):
        response = client.get("/transcription/record", follow_redirects=False)
        assert response.status_code == 401

    def test_record_page_renders_for_auth_user(self, user_client):
        response = user_client.get("/transcription/record")
        assert response.status_code == 200
        assert "音声録音" in response.text
