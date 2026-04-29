import uuid

from app.models import (
    AudioFile,
    AudioSource,
    ChunkRefinementStatus,
    TranscriptionChunk,
    TranscriptionEngine,
    TranscriptionJob,
    TranscriptionStatus,
)
from app.services import transcript_output


def _job_with_segments() -> TranscriptionJob:
    audio_file = AudioFile(
        id=uuid.uuid4(),
        user_id=1,
        source=AudioSource.UPLOAD,
        original_filename="seminar.mp4",
        stored_filename="seminar.mp4",
        file_path="/tmp/seminar.mp4",
        file_size=123,
        mime_type="video/mp4",
        duration_seconds=65.0,
    )
    return TranscriptionJob(
        id=uuid.uuid4(),
        audio_file_id=audio_file.id,
        user_id=1,
        status=TranscriptionStatus.COMPLETED,
        engine=TranscriptionEngine.PARAKEET_JA,
        model_size="parakeet-tdt_ctc-0.6b-ja",
        result_text="こんにちは 続き どうですか",
        result_segments=[
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0, "text": "こんにちは"},
            {"speaker": "SPEAKER_00", "start": 1.0, "end": 2.0, "text": "続き"},
            {"speaker": "SPEAKER_01", "start": 3.0, "end": 4.0, "text": "どうですか"},
        ],
        audio_file=audio_file,
        enable_speaker_diarization=True,
    )


def test_build_speaker_text_collapses_consecutive_speaker_segments():
    text = transcript_output.build_speaker_text(_job_with_segments())

    assert "[00:00:00-00:00:02] SPEAKER_00: こんにちは 続き" in text
    assert "[00:00:03-00:00:04] SPEAKER_01: どうですか" in text


def test_build_webvtt_includes_timestamps_and_speakers():
    vtt = transcript_output.build_webvtt(_job_with_segments())

    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.000" in vtt
    assert "SPEAKER_00: こんにちは" in vtt


def test_build_summary_prompt_context_prefers_speaker_labelled_text():
    context = transcript_output.build_summary_prompt_context(_job_with_segments())

    assert context["filename"] == "seminar.mp4"
    assert context["engine"] == "parakeet_ja"
    assert "SPEAKER_00" in str(context["text"])
    assert "SPEAKER_00" in str(context["speaker_text"])
    assert context["raw_text"] == "こんにちは 続き どうですか"


def test_build_summary_prompt_context_exposes_refined_and_raw_text():
    job = _job_with_segments()
    job.chunks = [
        TranscriptionChunk(
            transcription_job_id=job.id,
            user_id=job.user_id,
            chunk_index=0,
            start_seconds=0.0,
            end_seconds=10.0,
            raw_text="生チャンク",
            refined_text="本文整形後チャンク",
            refinement_status=ChunkRefinementStatus.COMPLETED,
        )
    ]

    context = transcript_output.build_summary_prompt_context(job)

    assert context["text"] == "本文整形後チャンク"
    assert context["refined_text"] == "本文整形後チャンク"
    assert context["raw_text"] == "こんにちは 続き どうですか"
    assert "SPEAKER_00" in str(context["speaker_text"])
