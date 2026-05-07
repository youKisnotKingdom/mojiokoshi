"""Database-backed runtime overrides for selected application settings."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import AppSetting

logger = logging.getLogger(__name__)

SettingType = Literal["str", "int", "float", "bool"]


@dataclass(frozen=True)
class RuntimeSettingDefinition:
    key: str
    env_name: str
    label: str
    category: str
    value_type: SettingType
    description: str = ""
    choices: tuple[tuple[str, str], ...] = ()
    sensitive: bool = False
    min_value: float | None = None
    max_value: float | None = None
    required: bool = False

    def parse(self, raw_value: Any) -> str | int | float | bool:
        if self.value_type == "bool":
            return _parse_bool(raw_value)

        text = "" if raw_value is None else str(raw_value).strip()
        if self.required and not text:
            raise ValueError("入力してください")

        if self.value_type == "str":
            if self.choices and text not in {value for value, _label in self.choices}:
                raise ValueError("選択肢から選んでください")
            return text

        if not text:
            raise ValueError("数値を入力してください")

        try:
            if self.value_type == "int":
                value = int(text)
            elif self.value_type == "float":
                value = float(text)
            else:
                raise ValueError("未対応の設定型です")
        except ValueError as exc:
            raise ValueError("数値として解釈できません") from exc

        if self.min_value is not None and value < self.min_value:
            raise ValueError(f"{self.min_value:g} 以上で入力してください")
        if self.max_value is not None and value > self.max_value:
            raise ValueError(f"{self.max_value:g} 以下で入力してください")
        return value

    def serialize(self, value: Any) -> str:
        if self.value_type == "bool":
            return "true" if bool(value) else "false"
        return "" if value is None else str(value)

    def display(self, value: Any) -> str:
        if self.sensitive:
            return "設定済み" if self.serialize(value) else "未設定"
        if self.value_type == "bool":
            return "on" if bool(value) else "off"
        return self.serialize(value) or "-"


SETTING_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("ui", "画面表示"),
    ("llm", "LLM処理"),
    ("refinement_llm", "精緻化LLM"),
    ("transcription", "文字起こし"),
    ("speaker", "話者分離"),
    ("worker", "Worker"),
    ("ldap", "LDAP"),
)


EDITABLE_SETTINGS: tuple[RuntimeSettingDefinition, ...] = (
    RuntimeSettingDefinition(
        "show_next_actions",
        "SHOW_NEXT_ACTIONS",
        "次の操作を表示",
        "ui",
        "bool",
        "文字起こし結果や LLM 結果の画面に、追加操作の導線を表示します。",
    ),
    RuntimeSettingDefinition(
        "llm_api_base_url",
        "LLM_API_BASE_URL",
        "LLM API URL",
        "llm",
        "str",
        required=True,
    ),
    RuntimeSettingDefinition(
        "llm_api_key",
        "LLM_API_KEY",
        "LLM API Key",
        "llm",
        "str",
        sensitive=True,
    ),
    RuntimeSettingDefinition(
        "llm_model_name",
        "LLM_MODEL_NAME",
        "LLM モデル名",
        "llm",
        "str",
        required=True,
    ),
    RuntimeSettingDefinition(
        "llm_max_tokens",
        "LLM_MAX_TOKENS",
        "最大トークン数",
        "llm",
        "int",
        min_value=1,
    ),
    RuntimeSettingDefinition(
        "llm_temperature",
        "LLM_TEMPERATURE",
        "temperature",
        "llm",
        "float",
        min_value=0,
        max_value=2,
    ),
    RuntimeSettingDefinition(
        "llm_timeout",
        "LLM_TIMEOUT",
        "LLM タイムアウト秒",
        "llm",
        "int",
        min_value=1,
    ),
    RuntimeSettingDefinition(
        "auto_llm_prompt_template_names",
        "AUTO_LLM_PROMPT_TEMPLATE_NAMES",
        "自動実行プロンプト名",
        "llm",
        "str",
        "カンマ区切り",
    ),
    RuntimeSettingDefinition(
        "chunk_refinement_llm_api_base_url",
        "CHUNK_REFINEMENT_LLM_API_BASE_URL",
        "精緻化 LLM API URL",
        "refinement_llm",
        "str",
        "空欄の場合は LLM処理 の API URL を使います。",
    ),
    RuntimeSettingDefinition(
        "chunk_refinement_llm_api_key",
        "CHUNK_REFINEMENT_LLM_API_KEY",
        "精緻化 LLM API Key",
        "refinement_llm",
        "str",
        "空欄の場合、専用 API URL 設定時は認証なし、未設定時は LLM処理 の API Key を使います。",
        sensitive=True,
    ),
    RuntimeSettingDefinition(
        "chunk_refinement_llm_model_name",
        "CHUNK_REFINEMENT_LLM_MODEL_NAME",
        "精緻化 LLM モデル名",
        "refinement_llm",
        "str",
        "空欄の場合は LLM処理 のモデル名を使います。",
    ),
    RuntimeSettingDefinition(
        "chunk_refinement_llm_temperature",
        "CHUNK_REFINEMENT_LLM_TEMPERATURE",
        "精緻化 temperature",
        "refinement_llm",
        "float",
        min_value=0,
        max_value=2,
    ),
    RuntimeSettingDefinition(
        "chunk_refinement_llm_timeout",
        "CHUNK_REFINEMENT_LLM_TIMEOUT",
        "精緻化タイムアウト秒",
        "refinement_llm",
        "int",
        "0 の場合は LLM処理 のタイムアウトを使います。",
        min_value=0,
    ),
    RuntimeSettingDefinition(
        "enable_chunk_llm_refinement",
        "ENABLE_CHUNK_LLM_REFINEMENT",
        "チャンク単位の LLM 整形",
        "refinement_llm",
        "bool",
    ),
    RuntimeSettingDefinition(
        "llm_chunk_refinement_max_input_chars",
        "LLM_CHUNK_REFINEMENT_MAX_INPUT_CHARS",
        "チャンク整形の最大入力文字数",
        "refinement_llm",
        "int",
        min_value=1,
    ),
    RuntimeSettingDefinition(
        "llm_chunk_refinement_max_output_tokens",
        "LLM_CHUNK_REFINEMENT_MAX_OUTPUT_TOKENS",
        "チャンク整形の最大出力トークン",
        "refinement_llm",
        "int",
        min_value=1,
    ),
    RuntimeSettingDefinition(
        "llm_chunk_refinement_context_chars",
        "LLM_CHUNK_REFINEMENT_CONTEXT_CHARS",
        "チャンク整形の前後文脈文字数",
        "refinement_llm",
        "int",
        min_value=0,
    ),
    RuntimeSettingDefinition(
        "default_transcription_engine",
        "DEFAULT_TRANSCRIPTION_ENGINE",
        "既定の文字起こしエンジン",
        "transcription",
        "str",
        choices=(
            ("parakeet_ja", "parakeet_ja"),
            ("faster_whisper", "faster_whisper"),
            ("whisper", "whisper"),
            ("qwen_asr", "qwen_asr"),
        ),
        required=True,
    ),
    RuntimeSettingDefinition(
        "whisper_model_size",
        "WHISPER_MODEL_SIZE",
        "Whisper モデルサイズ",
        "transcription",
        "str",
        required=True,
    ),
    RuntimeSettingDefinition(
        "whisper_device",
        "WHISPER_DEVICE",
        "Whisper デバイス",
        "transcription",
        "str",
        required=True,
    ),
    RuntimeSettingDefinition(
        "whisper_language",
        "WHISPER_LANGUAGE",
        "文字起こし言語",
        "transcription",
        "str",
    ),
    RuntimeSettingDefinition(
        "parakeet_chunk_seconds",
        "PARAKEET_CHUNK_SECONDS",
        "Parakeet チャンク秒数",
        "transcription",
        "int",
        min_value=1,
    ),
    RuntimeSettingDefinition(
        "parakeet_sample_rate",
        "PARAKEET_SAMPLE_RATE",
        "Parakeet サンプルレート",
        "transcription",
        "int",
        min_value=1,
    ),
    RuntimeSettingDefinition(
        "max_upload_size",
        "MAX_UPLOAD_SIZE",
        "最大アップロードサイズ bytes",
        "transcription",
        "int",
        min_value=1,
    ),
    RuntimeSettingDefinition(
        "audio_retention_days",
        "AUDIO_RETENTION_DAYS",
        "音声ファイル保持日数",
        "transcription",
        "int",
        min_value=0,
    ),
    RuntimeSettingDefinition(
        "enable_realtime_transcription",
        "ENABLE_REALTIME_TRANSCRIPTION",
        "リアルタイム録音 UI",
        "transcription",
        "bool",
    ),
    RuntimeSettingDefinition(
        "enable_speaker_diarization",
        "ENABLE_SPEAKER_DIARIZATION",
        "話者分離",
        "speaker",
        "bool",
    ),
    RuntimeSettingDefinition(
        "speaker_diarization_model_id",
        "SPEAKER_DIARIZATION_MODEL_ID",
        "話者分離モデル ID",
        "speaker",
        "str",
    ),
    RuntimeSettingDefinition(
        "speaker_diarization_model_path",
        "SPEAKER_DIARIZATION_MODEL_PATH",
        "話者分離モデルパス",
        "speaker",
        "str",
    ),
    RuntimeSettingDefinition(
        "speaker_diarization_device",
        "SPEAKER_DIARIZATION_DEVICE",
        "話者分離デバイス",
        "speaker",
        "str",
        choices=(("auto", "auto"), ("cpu", "cpu"), ("cuda", "cuda")),
        required=True,
    ),
    RuntimeSettingDefinition(
        "speaker_diarization_min_speakers",
        "SPEAKER_DIARIZATION_MIN_SPEAKERS",
        "話者数 min",
        "speaker",
        "int",
        min_value=0,
    ),
    RuntimeSettingDefinition(
        "speaker_diarization_max_speakers",
        "SPEAKER_DIARIZATION_MAX_SPEAKERS",
        "話者数 max",
        "speaker",
        "int",
        min_value=0,
    ),
    RuntimeSettingDefinition(
        "huggingface_token",
        "HUGGINGFACE_TOKEN",
        "Hugging Face Token",
        "speaker",
        "str",
        sensitive=True,
    ),
    RuntimeSettingDefinition(
        "worker_poll_interval",
        "WORKER_POLL_INTERVAL",
        "ポーリング間隔秒",
        "worker",
        "float",
        min_value=0.1,
    ),
    RuntimeSettingDefinition(
        "worker_transcription_concurrency",
        "WORKER_TRANSCRIPTION_CONCURRENCY",
        "文字起こし並列数",
        "worker",
        "int",
        min_value=0,
    ),
    RuntimeSettingDefinition(
        "worker_chunk_refinement_concurrency",
        "WORKER_CHUNK_REFINEMENT_CONCURRENCY",
        "チャンク整形並列数",
        "worker",
        "int",
        min_value=0,
    ),
    RuntimeSettingDefinition(
        "worker_summary_concurrency",
        "WORKER_SUMMARY_CONCURRENCY",
        "LLM 処理並列数",
        "worker",
        "int",
        min_value=0,
    ),
    RuntimeSettingDefinition(
        "worker_speaker_diarization_concurrency",
        "WORKER_SPEAKER_DIARIZATION_CONCURRENCY",
        "話者分離並列数",
        "worker",
        "int",
        min_value=0,
    ),
    RuntimeSettingDefinition(
        "worker_transcription_stale_timeout_seconds",
        "WORKER_TRANSCRIPTION_STALE_TIMEOUT_SECONDS",
        "文字起こし stale 秒",
        "worker",
        "int",
        min_value=0,
    ),
    RuntimeSettingDefinition(
        "worker_chunk_refinement_stale_timeout_seconds",
        "WORKER_CHUNK_REFINEMENT_STALE_TIMEOUT_SECONDS",
        "チャンク整形 stale 秒",
        "worker",
        "int",
        min_value=0,
    ),
    RuntimeSettingDefinition(
        "worker_summary_stale_timeout_seconds",
        "WORKER_SUMMARY_STALE_TIMEOUT_SECONDS",
        "LLM 処理 stale 秒",
        "worker",
        "int",
        min_value=0,
    ),
    RuntimeSettingDefinition(
        "worker_speaker_diarization_stale_timeout_seconds",
        "WORKER_SPEAKER_DIARIZATION_STALE_TIMEOUT_SECONDS",
        "話者分離 stale 秒",
        "worker",
        "int",
        min_value=0,
    ),
    RuntimeSettingDefinition(
        "worker_cleanup_interval_seconds",
        "WORKER_CLEANUP_INTERVAL_SECONDS",
        "音声削除チェック間隔秒",
        "worker",
        "int",
        "期限切れ音声ファイルの削除チェック間隔。0 の場合は自動削除チェックを停止します。",
        min_value=0,
    ),
    RuntimeSettingDefinition(
        "ldap_enabled",
        "LDAP_ENABLED",
        "LDAP ログイン",
        "ldap",
        "bool",
    ),
    RuntimeSettingDefinition(
        "ldap_server_uri",
        "LDAP_SERVER_URI",
        "LDAP server URI",
        "ldap",
        "str",
    ),
    RuntimeSettingDefinition(
        "ldap_bind_dn",
        "LDAP_BIND_DN",
        "LDAP bind DN",
        "ldap",
        "str",
    ),
    RuntimeSettingDefinition(
        "ldap_bind_password",
        "LDAP_BIND_PASSWORD",
        "LDAP bind password",
        "ldap",
        "str",
        sensitive=True,
    ),
    RuntimeSettingDefinition(
        "ldap_user_base_dn",
        "LDAP_USER_BASE_DN",
        "LDAP user base DN",
        "ldap",
        "str",
    ),
    RuntimeSettingDefinition(
        "ldap_user_filter",
        "LDAP_USER_FILTER",
        "LDAP user filter",
        "ldap",
        "str",
    ),
    RuntimeSettingDefinition(
        "ldap_user_id_attribute",
        "LDAP_USER_ID_ATTRIBUTE",
        "LDAP user ID attribute",
        "ldap",
        "str",
    ),
    RuntimeSettingDefinition(
        "ldap_display_name_attribute",
        "LDAP_DISPLAY_NAME_ATTRIBUTE",
        "LDAP display name attribute",
        "ldap",
        "str",
    ),
    RuntimeSettingDefinition(
        "ldap_start_tls",
        "LDAP_START_TLS",
        "LDAP StartTLS",
        "ldap",
        "bool",
    ),
    RuntimeSettingDefinition(
        "ldap_connect_timeout",
        "LDAP_CONNECT_TIMEOUT",
        "LDAP 接続タイムアウト秒",
        "ldap",
        "int",
        min_value=1,
    ),
    RuntimeSettingDefinition(
        "ldap_default_role",
        "LDAP_DEFAULT_ROLE",
        "LDAP 既定ロール",
        "ldap",
        "str",
        choices=(("user", "user"), ("admin", "admin")),
        required=True,
    ),
    RuntimeSettingDefinition(
        "ldap_group_base_dn",
        "LDAP_GROUP_BASE_DN",
        "LDAP group base DN",
        "ldap",
        "str",
    ),
    RuntimeSettingDefinition(
        "ldap_group_filter",
        "LDAP_GROUP_FILTER",
        "LDAP group filter",
        "ldap",
        "str",
    ),
    RuntimeSettingDefinition(
        "ldap_admin_group_dn",
        "LDAP_ADMIN_GROUP_DN",
        "LDAP admin group DN",
        "ldap",
        "str",
    ),
)

EDITABLE_SETTINGS_BY_KEY = {definition.key: definition for definition in EDITABLE_SETTINGS}


def _parse_bool(raw_value: Any) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    text = "" if raw_value is None else str(raw_value).strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n", ""}:
        return False
    raise ValueError("on/off として解釈できません")


def _load_override_rows(db: Session) -> dict[str, AppSetting]:
    keys = list(EDITABLE_SETTINGS_BY_KEY)
    rows = db.execute(select(AppSetting).where(AppSetting.key.in_(keys))).scalars().all()
    return {row.key: row for row in rows}


def apply_runtime_settings(db: Session, target_settings: Settings | None = None) -> int:
    """Apply DB overrides to the process-local Settings object.

    The existing Settings instance is mutated so modules that imported
    ``settings = get_settings()`` see updated values after this function runs.
    """
    target = target_settings or get_settings()

    try:
        base = Settings()
        for definition in EDITABLE_SETTINGS:
            setattr(target, definition.key, getattr(base, definition.key))

        applied = 0
        for row in _load_override_rows(db).values():
            definition = EDITABLE_SETTINGS_BY_KEY.get(row.key)
            if not definition:
                continue
            try:
                setattr(target, definition.key, definition.parse(row.value))
                applied += 1
            except ValueError:
                logger.warning("Ignoring invalid runtime setting %s=%r", row.key, row.value)
        return applied
    except SQLAlchemyError as exc:
        db.rollback()
        logger.debug("Runtime settings are not available yet: %s", exc)
        return 0


def build_settings_view(
    db: Session,
    submitted_values: dict[str, str] | None = None,
    errors: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    settings = get_settings()
    try:
        overrides = _load_override_rows(db)
    except SQLAlchemyError:
        db.rollback()
        overrides = {}

    groups: list[dict[str, object]] = []
    errors = errors or {}

    for category_key, category_label in SETTING_CATEGORIES:
        items = []
        for definition in EDITABLE_SETTINGS:
            if definition.category != category_key:
                continue
            current_value = getattr(settings, definition.key)
            if submitted_values is not None and definition.key in submitted_values:
                input_value = submitted_values[definition.key]
            elif definition.sensitive:
                input_value = ""
            else:
                input_value = definition.serialize(current_value)

            items.append(
                {
                    "definition": definition,
                    "input_value": input_value,
                    "current_value": definition.display(current_value),
                    "has_current_value": bool(definition.serialize(current_value)),
                    "is_overridden": definition.key in overrides,
                    "source": "管理画面" if definition.key in overrides else ".env/default",
                    "error": errors.get(definition.key),
                }
            )
        groups.append({"key": category_key, "label": category_label, "settings": items})

    return groups


def parse_settings_form(form) -> tuple[dict[str, str], dict[str, Any], set[str], dict[str, str]]:
    """Validate settings form data.

    Returns submitted display values, parsed values to persist, reset keys, and errors.
    Sensitive blank values are treated as unchanged.
    """
    reset_keys = {
        key
        for key in form.getlist("reset_keys")
        if key in EDITABLE_SETTINGS_BY_KEY
    }
    submitted_values: dict[str, str] = {}
    parsed_values: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for definition in EDITABLE_SETTINGS:
        if definition.key in reset_keys:
            continue

        if definition.value_type == "bool":
            raw_value = "true" if form.get(definition.key) else "false"
        else:
            raw_value = form.get(definition.key, "")
            raw_value = "" if raw_value is None else str(raw_value)

        submitted_values[definition.key] = raw_value

        if definition.sensitive and raw_value.strip() == "":
            continue

        try:
            parsed_values[definition.key] = definition.parse(raw_value)
        except ValueError as exc:
            errors[definition.key] = str(exc)

    return submitted_values, parsed_values, reset_keys, errors


def save_runtime_settings(
    db: Session,
    values: dict[str, Any],
    reset_keys: set[str],
    updated_by_id: int | None,
) -> None:
    base = Settings()

    for key in reset_keys:
        row = db.get(AppSetting, key)
        if row is not None:
            db.delete(row)

    for key, value in values.items():
        definition = EDITABLE_SETTINGS_BY_KEY[key]
        serialized_value = definition.serialize(value)
        base_value = definition.serialize(getattr(base, key))
        row = db.get(AppSetting, key)
        if serialized_value == base_value:
            if row is not None:
                db.delete(row)
            continue

        if row is None:
            row = AppSetting(key=key, value=serialized_value)
            db.add(row)
        else:
            row.value = serialized_value
        row.updated_by_id = updated_by_id

    db.commit()
    apply_runtime_settings(db)
