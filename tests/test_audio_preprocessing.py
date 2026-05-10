"""Tests for ASR audio preprocessing."""
from types import SimpleNamespace

from app.services import transcription


def test_prepare_audio_for_asr_light_mode_adds_safe_filters(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(transcription.settings, "audio_preprocessing_mode", "light")
    monkeypatch.setattr(transcription, "_run_media_command", lambda command: commands.append(command))

    transcription._prepare_audio_for_asr(tmp_path / "input.mp4", tmp_path / "output.wav", 16000)

    command = commands[0]
    assert command[:4] == ["ffmpeg", "-y", "-i", str(tmp_path / "input.mp4")]
    assert "-ac" in command
    assert command[command.index("-ac") + 1] == "1"
    assert "-ar" in command
    assert command[command.index("-ar") + 1] == "16000"
    assert "-af" in command
    filters = command[command.index("-af") + 1]
    assert "highpass=f=80" in filters
    assert "lowpass=f=7600" in filters
    assert "dynaudnorm=f=250:g=8:p=0.95" in filters
    assert "afftdn" not in filters
    assert command[-3:] == ["-c:a", "pcm_s16le", str(tmp_path / "output.wav")]


def test_prepare_audio_for_asr_off_mode_only_converts_format(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(transcription.settings, "audio_preprocessing_mode", "off")
    monkeypatch.setattr(transcription, "_run_media_command", lambda command: commands.append(command))

    transcription._prepare_audio_for_asr(tmp_path / "input.wav", tmp_path / "output.wav", 16000)

    command = commands[0]
    assert "-af" not in command
    assert command[-3:] == ["-c:a", "pcm_s16le", str(tmp_path / "output.wav")]


def test_prepare_audio_for_asr_denoise_mode_adds_noise_filter(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(transcription.settings, "audio_preprocessing_mode", "denoise")
    monkeypatch.setattr(transcription, "_run_media_command", lambda command: commands.append(command))

    transcription._prepare_audio_for_asr(tmp_path / "input.wav", tmp_path / "output.wav", 16000)

    command = commands[0]
    filters = command[command.index("-af") + 1]
    assert "afftdn=nf=-25" in filters


def test_faster_whisper_uses_preprocessed_audio_when_enabled(tmp_path, monkeypatch):
    commands = []
    transcribed_paths = []
    monkeypatch.setattr(transcription.settings, "audio_preprocessing_mode", "light")
    monkeypatch.setattr(transcription, "_run_media_command", lambda command: commands.append(command))

    class FakeWhisperModel:
        def transcribe(self, audio_path, **kwargs):
            transcribed_paths.append(audio_path)
            return (
                [SimpleNamespace(text=" テスト ", start=0.0, end=1.0, words=[])],
                SimpleNamespace(language="ja", language_probability=1.0),
            )

    monkeypatch.setattr(transcription, "get_whisper_model", lambda *args, **kwargs: FakeWhisperModel())

    source = tmp_path / "input.mp4"
    source.write_bytes(b"fake")
    segments = list(transcription.transcribe_audio_sync(str(source), language="ja", device="cpu"))

    assert commands
    assert transcribed_paths
    assert transcribed_paths[0].endswith("preprocessed.wav")
    assert segments == [{"text": "テスト", "start": 0.0, "end": 1.0, "words": []}]


def test_faster_whisper_keeps_source_audio_when_preprocessing_is_off(tmp_path, monkeypatch):
    commands = []
    transcribed_paths = []
    monkeypatch.setattr(transcription.settings, "audio_preprocessing_mode", "off")
    monkeypatch.setattr(transcription, "_run_media_command", lambda command: commands.append(command))

    class FakeWhisperModel:
        def transcribe(self, audio_path, **kwargs):
            transcribed_paths.append(audio_path)
            return (
                [SimpleNamespace(text=" テスト ", start=0.0, end=1.0, words=[])],
                SimpleNamespace(language="ja", language_probability=1.0),
            )

    monkeypatch.setattr(transcription, "get_whisper_model", lambda *args, **kwargs: FakeWhisperModel())

    source = tmp_path / "input.wav"
    source.write_bytes(b"fake")
    list(transcription.transcribe_audio_sync(str(source), language="ja", device="cpu"))

    assert commands == []
    assert transcribed_paths == [str(source)]
