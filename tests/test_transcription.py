"""Tests for transcription endpoints."""
import io
import re


def get_csrf_token(client, url="/transcription/upload"):
    response = client.get(url)
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    return match.group(1) if match else ""


class TestUploadPage:
    def test_upload_page_requires_auth(self, client):
        # Unauthenticated access returns 401 (not a redirect)
        response = client.get("/transcription/upload", follow_redirects=False)
        assert response.status_code == 401

    def test_upload_page_renders_for_auth_user(self, user_client):
        response = user_client.get("/transcription/upload")
        assert response.status_code == 200
        assert "音声アップロード" in response.text

    def test_upload_page_has_csrf_token(self, user_client):
        response = user_client.get("/transcription/upload")
        assert 'name="csrf_token"' in response.text


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

    def test_missing_csrf_rejected(self, user_client):
        response = user_client.post(
            "/transcription/upload",
            data={"engine": "faster_whisper", "model_size": "large", "csrf_token": ""},
            files={"file": ("test.wav", io.BytesIO(b"fake audio"), "audio/wav")},
        )
        assert response.status_code == 403

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
