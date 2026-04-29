"""Tests for transcription endpoints."""
import io
import re

from sqlalchemy import select

from app.models import TranscriptionEngine, TranscriptionJob


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

    def test_upload_page_defaults_to_parakeet_and_japanese(self, user_client):
        response = user_client.get("/transcription/upload")

        assert response.status_code == 200
        assert re.search(r'<option value="parakeet_ja"[^>]*selected', response.text)
        assert re.search(r'<option value="ja"[^>]*selected', response.text)
        assert 'id="model-size-field" class="hidden"' in response.text
        assert "Whisper用モデルサイズ" in response.text
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
            data={"engine": "faster_whisper", "model_size": "large", "csrf_token": csrf},
            files={"file": ("test.txt", io.BytesIO(b"not audio"), "text/plain")},
        )
        assert response.status_code == 400
        assert "無効なファイル形式" in response.text
        assert "音声または動画ファイル" in response.text

    def test_default_upload_uses_parakeet_and_japanese(self, user_client, db):
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
        assert job.language == "ja"

    def test_missing_csrf_rejected(self, user_client):
        response = user_client.post(
            "/transcription/upload",
            data={"engine": "faster_whisper", "model_size": "large", "csrf_token": ""},
            files={"file": ("test.wav", io.BytesIO(b"fake audio"), "audio/wav")},
        )
        assert response.status_code == 403
        assert "CSRFトークンが無効です" in response.text

    def test_ajax_missing_csrf_returns_inline_error_payload(self, user_client):
        response = user_client.post(
            "/transcription/upload",
            data={"engine": "faster_whisper", "model_size": "large", "csrf_token": ""},
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


class TestRecordPage:
    def test_record_page_requires_auth(self, client):
        response = client.get("/transcription/record", follow_redirects=False)
        assert response.status_code == 401

    def test_record_page_renders_for_auth_user(self, user_client):
        response = user_client.get("/transcription/record")
        assert response.status_code == 200
        assert "音声録音" in response.text
