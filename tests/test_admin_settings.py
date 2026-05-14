"""Tests for admin-editable runtime settings."""
import re

from app.config import get_settings
from app.models import AppSetting
from app.services import runtime_settings


def get_csrf_token(client):
    response = client.get("/admin/settings")
    assert response.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    return match.group(1) if match else ""


def build_settings_form(csrf_token: str, overrides: dict[str, object] | None = None):
    settings = get_settings()
    data: dict[str, str] = {"csrf_token": csrf_token}
    for definition in runtime_settings.EDITABLE_SETTINGS:
        value = getattr(settings, definition.key)
        if definition.sensitive:
            data[definition.key] = ""
        elif definition.value_type == "bool":
            if bool(value):
                data[definition.key] = "on"
        else:
            data[definition.key] = definition.serialize(value)

    for key, value in (overrides or {}).items():
        definition = runtime_settings.EDITABLE_SETTINGS_BY_KEY[key]
        if definition.value_type == "bool":
            if value:
                data[key] = "on"
            else:
                data.pop(key, None)
        else:
            data[key] = str(value)
    return data


class TestAdminSettings:
    def test_admin_can_view_settings(self, admin_client):
        response = admin_client.get("/admin/settings")

        assert response.status_code == 200
        assert "管理設定" in response.text
        assert "画面表示" in response.text
        assert "SHOW_NEXT_ACTIONS" in response.text
        assert "LLM_API_BASE_URL" in response.text
        assert "AUDIO_PREPROCESSING_MODE" in response.text
        assert "reazon_nemo_v2" in response.text
        assert "プロンプト" in response.text

    def test_regular_user_cannot_view_settings(self, user_client):
        response = user_client.get("/admin/settings", follow_redirects=False)

        assert response.status_code == 403

    def test_admin_can_update_runtime_setting(self, admin_client, db):
        settings = get_settings()
        original_values = {
            definition.key: getattr(settings, definition.key)
            for definition in runtime_settings.EDITABLE_SETTINGS
        }
        try:
            csrf = get_csrf_token(admin_client)
            response = admin_client.post(
                "/admin/settings",
                data=build_settings_form(
                    csrf,
                    {
                        "llm_model_name": "admin-selected-model",
                        "enable_chunk_llm_refinement": False,
                        "show_next_actions": True,
                    },
                ),
                follow_redirects=False,
            )

            assert response.status_code == 303
            assert response.headers["location"] == "/admin/settings?saved=1"
            assert db.get(AppSetting, "llm_model_name").value == "admin-selected-model"
            assert db.get(AppSetting, "show_next_actions").value == "true"
            assert get_settings().llm_model_name == "admin-selected-model"
            assert get_settings().enable_chunk_llm_refinement is False
            assert get_settings().show_next_actions is True
        finally:
            for key, value in original_values.items():
                setattr(settings, key, value)

    def test_admin_can_change_default_transcription_engine(self, admin_client, db):
        settings = get_settings()
        original_engine = settings.default_transcription_engine
        try:
            csrf = get_csrf_token(admin_client)
            response = admin_client.post(
                "/admin/settings",
                data=build_settings_form(
                    csrf,
                    {"default_transcription_engine": "parakeet_ja"},
                ),
                follow_redirects=False,
            )

            assert response.status_code == 303
            assert response.headers["location"] == "/admin/settings?saved=1"
            assert db.get(AppSetting, "default_transcription_engine").value == "parakeet_ja"
            assert get_settings().default_transcription_engine == "parakeet_ja"
        finally:
            settings.default_transcription_engine = original_engine

    def test_invalid_runtime_setting_is_rejected(self, admin_client):
        settings = get_settings()
        original_max_tokens = settings.llm_max_tokens
        try:
            csrf = get_csrf_token(admin_client)
            response = admin_client.post(
                "/admin/settings",
                data=build_settings_form(csrf, {"llm_max_tokens": 0}),
            )

            assert response.status_code == 400
            assert "1 以上で入力してください" in response.text
            assert get_settings().llm_max_tokens == original_max_tokens
        finally:
            settings.llm_max_tokens = original_max_tokens

    def test_admin_can_reset_setting_to_env_default(self, admin_client, db, admin_user):
        settings = get_settings()
        original_model_name = settings.llm_model_name
        try:
            row = AppSetting(
                key="llm_model_name",
                value="db-override-model",
                updated_by_id=admin_user.id,
            )
            db.add(row)
            db.commit()
            runtime_settings.apply_runtime_settings(db)
            assert get_settings().llm_model_name == "db-override-model"

            csrf = get_csrf_token(admin_client)
            data = build_settings_form(csrf)
            data["reset_keys"] = "llm_model_name"
            response = admin_client.post(
                "/admin/settings",
                data=data,
                follow_redirects=False,
            )

            assert response.status_code == 303
            assert db.get(AppSetting, "llm_model_name") is None
            assert get_settings().llm_model_name == original_model_name
        finally:
            settings.llm_model_name = original_model_name
