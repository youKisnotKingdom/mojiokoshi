import asyncio
import uuid

from sqlalchemy import select

from app.models import (
    AudioFile,
    AudioSource,
    ChunkRefinementStatus,
    SpeakerDiarizationStatus,
    Summary,
    SummaryStatus,
    TranscriptionChunk,
    TranscriptionEngine,
    TranscriptionJob,
    TranscriptionStatus,
)
from app.services import summarization, transcript_output, transcription


def _job(
    db,
    user_id: int,
    file_path: str = "/tmp/seminar.wav",
    duration_seconds: float | None = 20.0,
) -> TranscriptionJob:
    audio_file = AudioFile(
        user_id=user_id,
        source=AudioSource.UPLOAD,
        original_filename="seminar.wav",
        stored_filename="seminar.wav",
        file_path=file_path,
        file_size=123,
        mime_type="audio/wav",
        duration_seconds=duration_seconds,
    )
    job = TranscriptionJob(
        id=uuid.uuid4(),
        audio_file=audio_file,
        user_id=user_id,
        status=TranscriptionStatus.PROCESSING,
        engine=TranscriptionEngine.PARAKEET_JA,
        model_size="parakeet-tdt_ctc-0.6b-ja",
        language="ja",
    )
    db.add(audio_file)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_transcription_job_persists_asr_chunks(db, regular_user, tmp_path, monkeypatch):
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"fake")
    job = _job(db, regular_user.id, str(audio_path))

    def fake_transcribe(*args, **kwargs):
        yield {
            "text": "最初のチャンクです",
            "start": 0.0,
            "end": 5.0,
            "chunk_index": 0,
            "chunk_start": 0.0,
            "chunk_end": 10.0,
            "words": [],
        }
        yield {
            "text": "同じチャンクの続きです",
            "start": 5.0,
            "end": 10.0,
            "chunk_index": 0,
            "chunk_start": 0.0,
            "chunk_end": 10.0,
            "words": [],
        }
        yield {
            "text": "次のチャンクです",
            "start": 10.0,
            "end": 20.0,
            "chunk_index": 1,
            "chunk_start": 10.0,
            "chunk_end": 20.0,
            "words": [],
        }

    monkeypatch.setattr(transcription, "transcribe_batch_job_sync", fake_transcribe)
    monkeypatch.setattr(transcription.settings, "enable_speaker_diarization", False)
    monkeypatch.setattr(summarization.settings, "enable_chunk_llm_refinement", True)

    assert asyncio.run(transcription.process_transcription_job(db, job)) is True

    chunks = db.execute(
        select(TranscriptionChunk)
        .where(TranscriptionChunk.transcription_job_id == job.id)
        .order_by(TranscriptionChunk.chunk_index)
    ).scalars().all()
    assert len(chunks) == 2
    assert chunks[0].raw_text == "最初のチャンクです 同じチャンクの続きです"
    assert chunks[0].start_seconds == 0.0
    assert chunks[0].end_seconds == 10.0
    assert chunks[0].refinement_status == ChunkRefinementStatus.PENDING
    assert chunks[1].raw_text == "次のチャンクです"


def test_transcription_job_completes_before_speaker_diarization(db, regular_user, tmp_path, monkeypatch):
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"fake")
    job = _job(db, regular_user.id, str(audio_path))
    job.enable_speaker_diarization = True
    job.speaker_diarization_status = SpeakerDiarizationStatus.PENDING
    db.commit()

    def fake_transcribe(*args, **kwargs):
        yield {
            "text": "話者分離は後から実行します",
            "start": 0.0,
            "end": 10.0,
            "chunk_index": 0,
            "chunk_start": 0.0,
            "chunk_end": 10.0,
            "words": [],
        }

    def fail_diarization(*args, **kwargs):
        raise AssertionError("speaker diarization must not block ASR completion")

    monkeypatch.setattr(transcription, "transcribe_batch_job_sync", fake_transcribe)
    monkeypatch.setattr(transcription.settings, "enable_speaker_diarization", True)
    monkeypatch.setattr(transcription.speaker_diarization_service, "diarize_audio", fail_diarization)

    assert asyncio.run(transcription.process_transcription_job(db, job)) is True

    db.refresh(job)
    assert job.status == TranscriptionStatus.COMPLETED
    assert job.result_text == "話者分離は後から実行します"
    assert job.speaker_diarization_status == SpeakerDiarizationStatus.PENDING
    assert job.speaker_diarization_started_at is None


def test_speaker_diarization_job_attaches_labels_after_asr_completion(db, regular_user, tmp_path, monkeypatch):
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"fake")
    job = _job(db, regular_user.id, str(audio_path))
    job.status = TranscriptionStatus.COMPLETED
    job.result_text = "こんにちは どうぞ"
    job.result_segments = [
        {"text": "こんにちは", "start": 0.0, "end": 1.0, "words": []},
        {"text": "どうぞ", "start": 1.0, "end": 2.0, "words": []},
    ]
    job.enable_speaker_diarization = True
    job.speaker_diarization_status = SpeakerDiarizationStatus.PROCESSING
    db.commit()

    monkeypatch.setattr(transcription.settings, "enable_speaker_diarization", True)
    monkeypatch.setattr(
        transcription.speaker_diarization_service,
        "diarize_audio",
        lambda path: [
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 1.1},
            {"speaker": "SPEAKER_01", "start": 1.1, "end": 2.0},
        ],
    )

    assert asyncio.run(transcription.process_speaker_diarization_job(db, job)) is True

    db.refresh(job)
    assert job.status == TranscriptionStatus.COMPLETED
    assert job.speaker_diarization_status == SpeakerDiarizationStatus.COMPLETED
    assert job.speaker_diarization_turns
    assert job.result_segments[0]["speaker"] == "SPEAKER_00"


def test_transcription_job_probes_missing_duration_for_progress(db, regular_user, tmp_path, monkeypatch):
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"fake")
    job = _job(db, regular_user.id, str(audio_path), duration_seconds=None)

    def fake_transcribe(*args, **kwargs):
        yield {
            "text": "進捗確認",
            "start": 0.0,
            "end": 10.0,
            "chunk_index": 0,
            "chunk_start": 0.0,
            "chunk_end": 10.0,
            "words": [],
        }

    monkeypatch.setattr(transcription, "_ffprobe_duration", lambda path: 10.0)
    monkeypatch.setattr(transcription, "transcribe_batch_job_sync", fake_transcribe)
    monkeypatch.setattr(transcription.settings, "enable_speaker_diarization", False)

    assert asyncio.run(transcription.process_transcription_job(db, job)) is True

    db.refresh(job.audio_file)
    db.refresh(job)
    assert job.audio_file.duration_seconds == 10.0
    assert job.progress_percent == 100.0


def test_process_chunk_refinement_updates_refined_text(db, regular_user, monkeypatch):
    job = _job(db, regular_user.id)
    chunk = summarization.create_or_update_transcription_chunk(
        db,
        job,
        chunk_index=0,
        start_seconds=0.0,
        end_seconds=10.0,
        raw_text="えー 今日は テストです",
        raw_segments=[],
    )

    monkeypatch.setattr(summarization.settings, "chunk_refinement_llm_temperature", 0.1)

    async def fake_call_llm_api(
        prompt,
        system_prompt=None,
        model=None,
        temperature=None,
        max_tokens=None,
        api_base=None,
        api_key=None,
        timeout=None,
    ):
        assert "対象チャンクの文字起こし" in prompt
        assert temperature == 0.1
        return summarization.LLMAPIResult(
            content="今日はテストです。",
            finish_reason="stop",
            usage={"completion_tokens": 10},
        )

    monkeypatch.setattr(summarization, "call_llm_api_with_metadata", fake_call_llm_api)

    assert asyncio.run(summarization.process_chunk_refinement(db, chunk)) is True

    db.refresh(chunk)
    assert chunk.refinement_status == ChunkRefinementStatus.COMPLETED
    assert chunk.refined_text == "今日はテストです。"
    assert chunk.token_usage["finish_reason"] == "stop"


def test_chunk_refinement_uses_dedicated_llm_settings(db, regular_user, monkeypatch):
    job = _job(db, regular_user.id)
    chunk = summarization.create_or_update_transcription_chunk(
        db,
        job,
        chunk_index=0,
        start_seconds=0.0,
        end_seconds=10.0,
        raw_text="CPU用モデルで整形します",
        raw_segments=[],
    )
    monkeypatch.setattr(summarization.settings, "llm_api_base_url", "http://summary-llm/v1")
    monkeypatch.setattr(summarization.settings, "llm_api_key", "summary-key")
    monkeypatch.setattr(summarization.settings, "llm_model_name", "summary-model")
    monkeypatch.setattr(
        summarization.settings,
        "chunk_refinement_llm_api_base_url",
        "http://cpu-refiner/v1",
    )
    monkeypatch.setattr(summarization.settings, "chunk_refinement_llm_api_key", "")
    monkeypatch.setattr(summarization.settings, "chunk_refinement_llm_model_name", "cpu-refiner")
    monkeypatch.setattr(summarization.settings, "chunk_refinement_llm_timeout", 45)

    captured = {}

    async def fake_call_llm_api(
        prompt,
        system_prompt=None,
        model=None,
        temperature=None,
        max_tokens=None,
        api_base=None,
        api_key=None,
        timeout=None,
    ):
        captured.update(
            {
                "model": model,
                "api_base": api_base,
                "api_key": api_key,
                "timeout": timeout,
            }
        )
        return summarization.LLMAPIResult(content="CPU用モデルで整形します。")

    monkeypatch.setattr(summarization, "call_llm_api_with_metadata", fake_call_llm_api)

    assert asyncio.run(summarization.process_chunk_refinement(db, chunk)) is True

    assert captured == {
        "model": "cpu-refiner",
        "api_base": "http://cpu-refiner/v1",
        "api_key": "",
        "timeout": 45,
    }


def test_chunk_refinement_preserves_raw_text_when_input_too_long(db, regular_user, monkeypatch):
    job = _job(db, regular_user.id)
    raw_text = "長い文字起こしです。" * 20
    chunk = summarization.create_or_update_transcription_chunk(
        db,
        job,
        chunk_index=0,
        start_seconds=0.0,
        end_seconds=10.0,
        raw_text=raw_text,
        raw_segments=[],
    )
    monkeypatch.setattr(summarization.settings, "llm_chunk_refinement_max_input_chars", 10)

    async def fake_call_llm_api(*args, **kwargs):
        raise AssertionError("too-long chunks should not be sent to the LLM")

    monkeypatch.setattr(summarization, "call_llm_api_with_metadata", fake_call_llm_api)

    assert asyncio.run(summarization.process_chunk_refinement(db, chunk)) is True

    db.refresh(chunk)
    assert chunk.refinement_status == ChunkRefinementStatus.COMPLETED
    assert chunk.refined_text == raw_text
    assert chunk.token_usage["skipped"] is True
    assert chunk.token_usage["skip_reason"] == "input_too_long"


def test_pending_chunk_refinement_blocks_final_summary_claim(db, regular_user):
    job = _job(db, regular_user.id)
    job.status = TranscriptionStatus.COMPLETED
    summary = Summary(
        transcription_job_id=job.id,
        user_id=regular_user.id,
        status=SummaryStatus.PENDING,
        model_name="test-model",
    )
    chunk = TranscriptionChunk(
        transcription_job_id=job.id,
        user_id=regular_user.id,
        chunk_index=0,
        start_seconds=0.0,
        end_seconds=10.0,
        raw_text="未処理チャンク",
        refinement_status=ChunkRefinementStatus.PENDING,
    )
    db.add_all([summary, chunk])
    db.commit()

    assert summarization.claim_pending_summaries(db) == []

    chunk.refinement_status = ChunkRefinementStatus.COMPLETED
    chunk.refined_text = "処理済みチャンク"
    db.commit()

    assert summarization.claim_pending_summaries(db) == [summary.id]


def test_summary_input_prefers_refined_chunks(db, regular_user):
    job = _job(db, regular_user.id)
    job.result_text = "生の全文"
    job.chunks = [
        TranscriptionChunk(
            transcription_job_id=job.id,
            user_id=regular_user.id,
            chunk_index=0,
            start_seconds=0.0,
            end_seconds=10.0,
            raw_text="生チャンク",
            refined_text="精緻化済みチャンク",
            refinement_status=ChunkRefinementStatus.COMPLETED,
        )
    ]

    text = transcript_output.build_summary_input_text(job)

    assert "精緻化済みチャンク" in text
    assert "生の全文" not in text
    assert "[00:00:00-00:00:10]" not in text


def test_refined_transcript_summary_assembles_chunks_without_full_llm(db, regular_user, monkeypatch):
    job = _job(db, regular_user.id)
    job.status = TranscriptionStatus.COMPLETED
    job.result_text = "生の全文"
    template = summarization.PromptTemplate(
        name="文字起こしの精緻化",
        system_prompt="system",
        user_prompt_template="{text}",
        is_active=True,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    db.add_all(
        [
            TranscriptionChunk(
                transcription_job_id=job.id,
                user_id=regular_user.id,
                chunk_index=0,
                start_seconds=0.0,
                end_seconds=10.0,
                raw_text="生チャンク1",
                refined_text="精緻化済みチャンク1",
                refinement_status=ChunkRefinementStatus.COMPLETED,
            ),
            TranscriptionChunk(
                transcription_job_id=job.id,
                user_id=regular_user.id,
                chunk_index=1,
                start_seconds=10.0,
                end_seconds=20.0,
                raw_text="生チャンク2",
                refined_text="精緻化済みチャンク2",
                refinement_status=ChunkRefinementStatus.COMPLETED,
            ),
        ]
    )
    summary = Summary(
        transcription_job_id=job.id,
        user_id=regular_user.id,
        status=SummaryStatus.PENDING,
        prompt_template_id=template.id,
        model_name="test-model",
    )
    db.add(summary)
    db.commit()
    db.refresh(summary)

    async def fail_full_llm(*args, **kwargs):
        raise AssertionError("full transcript LLM call should not run")

    monkeypatch.setattr(summarization, "summarize_text_with_metadata", fail_full_llm)

    assert asyncio.run(summarization.process_summary(db, summary)) is True

    db.refresh(summary)
    assert summary.status == SummaryStatus.COMPLETED
    assert "精緻化済みチャンク1" in summary.result_text
    assert "精緻化済みチャンク2" in summary.result_text
    assert "[00:00:00-00:00:10]" not in summary.result_text
    assert "[00:00:10-00:00:20]" not in summary.result_text
    assert summary.token_usage["source"] == "chunk_refinement"
    assert summary.token_usage["finish_reason"] == "assembled"
