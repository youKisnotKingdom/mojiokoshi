"""Tests for ASR audio preprocessing."""
from types import SimpleNamespace

from app.models import TranscriptionEngine
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


def test_reazon_nemo_transcription_preprocesses_and_chunks(tmp_path, monkeypatch):
    prepared_paths = []
    chunk_a = tmp_path / "chunk_0000.wav"
    chunk_b = tmp_path / "chunk_0001.wav"
    chunk_a.write_bytes(b"a")
    chunk_b.write_bytes(b"b")

    def fake_prepare(source, output_path, sample_rate):
        prepared_paths.append((source, output_path, sample_rate))
        output_path.write_bytes(b"prepared")
        return output_path

    class FakeReazonModel:
        def transcribe(self, paths, batch_size=1):
            assert batch_size == 1
            path = paths[0]
            if path.endswith("chunk_0000.wav"):
                return [SimpleNamespace(text="最初のチャンク")]
            return [SimpleNamespace(text="次のチャンク")]

    monkeypatch.setattr(transcription.settings, "audio_preprocessing_mode", "light")
    monkeypatch.setattr(transcription, "_prepare_audio_for_asr", fake_prepare)
    monkeypatch.setattr(transcription, "_split_audio_for_parakeet", lambda *_: [chunk_a, chunk_b])
    monkeypatch.setattr(transcription, "_ffprobe_duration", lambda path: 5.0)
    monkeypatch.setattr(transcription, "get_reazon_nemo_model", lambda device: FakeReazonModel())

    source = tmp_path / "input.mp4"
    source.write_bytes(b"fake")
    segments = list(transcription.transcribe_audio_reazon_nemo_sync(str(source), language="ja", device="cpu"))

    assert prepared_paths[0][0] == source
    assert prepared_paths[0][2] == 16000
    assert segments == [
        {
            "text": "最初のチャンク",
            "start": 0.0,
            "end": 5.0,
            "chunk_index": 0,
            "chunk_start": 0.0,
            "chunk_end": 5.0,
            "words": [],
            "language": "ja",
        },
        {
            "text": "次のチャンク",
            "start": 5.0,
            "end": 10.0,
            "chunk_index": 1,
            "chunk_start": 5.0,
            "chunk_end": 10.0,
            "words": [],
            "language": "ja",
        },
    ]


def test_batch_dispatch_supports_reazon_nemo(monkeypatch):
    monkeypatch.setattr(
        transcription,
        "transcribe_audio_reazon_nemo_sync",
        lambda *args, **kwargs: iter([{"text": "reazon"}]),
    )

    segments = list(
        transcription.transcribe_batch_job_sync(
            TranscriptionEngine.REAZON_NEMO_V2,
            "input.wav",
            "reazonspeech-nemo-v2",
            "ja",
            "cpu",
        )
    )

    assert segments == [{"text": "reazon"}]
