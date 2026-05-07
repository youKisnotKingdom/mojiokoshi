import re
import uuid
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.models import (
    AudioFile,
    AudioSource,
    ChunkRefinementStatus,
    PromptTemplate,
    Summary,
    SummaryStatus,
    TranscriptionChunk,
    TranscriptionEngine,
    TranscriptionJob,
    TranscriptionStatus,
    User,
    UserRole,
)
from app.time_utils import utc_now


def _completed_job(db, user_id: int) -> TranscriptionJob:
    audio_file = AudioFile(
        user_id=user_id,
        source=AudioSource.UPLOAD,
        original_filename="seminar.mp4",
        stored_filename="seminar.mp4",
        file_path="/tmp/seminar.mp4",
        file_size=123,
        mime_type="video/mp4",
        duration_seconds=65.0,
        expires_at=utc_now() + timedelta(days=30),
    )
    job = TranscriptionJob(
        id=uuid.uuid4(),
        audio_file=audio_file,
        user_id=user_id,
        status=TranscriptionStatus.COMPLETED,
        engine=TranscriptionEngine.PARAKEET_JA,
        model_size="parakeet-tdt_ctc-0.6b-ja",
        result_text="こんにちは 続き",
        result_segments=[
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0, "text": "こんにちは"},
            {"speaker": "SPEAKER_00", "start": 1.0, "end": 2.0, "text": "続き"},
        ],
        enable_speaker_diarization=True,
    )
    db.add(audio_file)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _make_source_file(db, job: TranscriptionJob, tmp_path, *, mime_type: str = "audio/wav") -> None:
    source_path = tmp_path / "source.wav"
    source_path.write_bytes(b"audio-bytes")
    job.audio_file.file_path = str(source_path)
    job.audio_file.mime_type = mime_type
    job.audio_file.original_filename = source_path.name
    db.commit()


def _other_user(db) -> User:
    from app.services.auth import get_password_hash

    user = User(
        user_id="000003",
        password_hash=get_password_hash("OtherPass1"),
        display_name="Guest User",
        role=UserRole.USER,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_job_detail_shows_download_and_summary_prompt_controls(user_client, db, regular_user):
    job = _completed_job(db, regular_user.id)

    response = user_client.get(f"/transcription/job/{job.id}")

    assert response.status_code == 200
    assert "文字起こし結果" in response.text
    assert "本文コピー" not in response.text
    assert "話者TXT" in response.text
    assert "LLM処理プロンプト" not in response.text
    assert "次の操作" not in response.text
    assert "Step 1" in response.text
    assert "Step 2" in response.text
    assert "処理ログ" not in response.text
    assert "処理詳細" in response.text
    assert "data-processing-details" in response.text
    assert "エンジン:" not in response.text
    assert "文字起こし設定" in response.text
    assert "parakeet_ja" in response.text
    assert "parakeet-tdt_ctc-0.6b-ja" in response.text
    assert "文字起こしとLLM処理の状態、完了後の結果を同じ流れで確認できます。" not in response.text
    assert "時刻は日本時間、経過は現在または完了時点まで" not in response.text
    assert "音声保持:" in response.text
    assert "あと30日" in response.text
    assert "文字起こし待機" in response.text
    assert "本文整形" in response.text
    assert "先頭だけ表示し、全文はプルダウンで確認できます" not in response.text
    assert "文字起こし全文を表示" in response.text
    assert "llm-result-panel" in response.text
    assert "llm-result-panel-meta" in response.text
    assert '<details id="llm-result-panel-meta"' in response.text
    assert "全文を別枠で表示しています" in response.text
    assert "max-h-96" not in response.text
    assert "captureLlmProgressScrollState" in response.text
    assert "restoreLlmProgressScrollState" in response.text


def test_logged_in_user_can_view_other_users_visible_job(user_client, db, tmp_path):
    other = _other_user(db)
    job = _completed_job(db, other.id)
    _make_source_file(db, job, tmp_path)
    summary = Summary(
        transcription_job_id=job.id,
        user_id=other.id,
        status=SummaryStatus.COMPLETED,
        result_text="# 共有できる結果\n本文",
        model_name="test-model",
    )
    db.add(summary)
    db.commit()
    db.refresh(summary)

    detail_response = user_client.get(f"/transcription/job/{job.id}")
    audio_response = user_client.get(f"/transcription/job/{job.id}/audio")
    transcript_response = user_client.get(f"/transcription/job/{job.id}/download/txt")
    summary_response = user_client.get(f"/summary/job/{summary.id}")
    summary_download_response = user_client.get(f"/summary/job/{summary.id}/download/md")

    assert detail_response.status_code == 200
    assert "Guest User" in detail_response.text
    assert f"/transcription/job/{job.id}/delete" not in detail_response.text
    assert audio_response.status_code == 200
    assert transcript_response.status_code == 200
    assert summary_response.status_code == 200
    assert "# 共有できる結果" in summary_response.text
    assert summary_download_response.status_code == 200


def test_logged_in_user_cannot_delete_other_users_job(user_client, db):
    other = _other_user(db)
    job = _completed_job(db, other.id)
    csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', user_client.get("/transcription/upload").text)
    csrf = csrf_match.group(1)

    response = user_client.post(
        f"/transcription/job/{job.id}/delete",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert db.get(TranscriptionJob, job.id) is not None


def test_logged_in_user_cannot_start_llm_for_other_users_job(user_client, db):
    other = _other_user(db)
    job = _completed_job(db, other.id)

    response = user_client.post(
        "/summary/api/create",
        json={"transcription_job_id": str(job.id)},
    )

    assert response.status_code == 404


def test_admin_can_delete_other_users_job(admin_client, db):
    other = _other_user(db)
    job = _completed_job(db, other.id)
    csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', admin_client.get(f"/transcription/job/{job.id}").text)
    csrf = csrf_match.group(1)

    response = admin_client.post(
        f"/transcription/job/{job.id}/delete",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert db.get(TranscriptionJob, job.id) is None


def test_job_detail_can_show_next_actions_when_enabled(user_client, db, regular_user):
    settings = get_settings()
    original_value = settings.show_next_actions
    try:
        settings.show_next_actions = True
        job = _completed_job(db, regular_user.id)

        response = user_client.get(f"/transcription/job/{job.id}")

        assert response.status_code == 200
        assert "次の操作" in response.text
        assert "LLM処理プロンプト" in response.text
        assert "next-actions" in response.text
    finally:
        settings.show_next_actions = original_value


def test_job_detail_shows_source_audio_player_and_seek_buttons(user_client, db, regular_user, tmp_path):
    job = _completed_job(db, regular_user.id)
    _make_source_file(db, job, tmp_path)
    db.add_all(
        [
            TranscriptionChunk(
                transcription_job_id=job.id,
                user_id=regular_user.id,
                chunk_index=0,
                start_seconds=0.0,
                end_seconds=10.0,
                raw_text="文字起こしチャンク1",
                refinement_status=ChunkRefinementStatus.COMPLETED,
            ),
            TranscriptionChunk(
                transcription_job_id=job.id,
                user_id=regular_user.id,
                chunk_index=1,
                start_seconds=10.0,
                end_seconds=20.0,
                raw_text="文字起こしチャンク2",
                refinement_status=ChunkRefinementStatus.COMPLETED,
            ),
        ]
    )
    db.commit()

    response = user_client.get(f"/transcription/job/{job.id}")

    assert response.status_code == 200
    assert "元音声" in response.text
    assert 'id="source-media"' in response.text
    assert f'/transcription/job/{job.id}/audio' in response.text
    assert "js-seek-audio" in response.text
    assert 'data-audio-seek="0.000"' in response.text
    assert 'data-audio-seek="10.000"' in response.text


def test_history_shows_audio_retention_remaining(user_client, db, regular_user):
    job = _completed_job(db, regular_user.id)

    response = user_client.get("/history/uploads")

    assert response.status_code == 200
    assert "音声保持:" in response.text
    assert "あと30日" in response.text
    assert "data-history-row" in response.text
    assert f'data-href="/transcription/job/{job.id}"' in response.text
    assert ">表示<" not in response.text
    assert "parakeet_ja" not in response.text
    assert "parakeet-tdt_ctc-0.6b-ja" not in response.text
    assert "登録者" in response.text
    assert "Test User" in response.text


def test_history_defaults_to_current_user_and_can_search_all(user_client, db, regular_user):
    _completed_job(db, regular_user.id)
    other = _other_user(db)
    other_job = _completed_job(db, other.id)
    other_job.audio_file.original_filename = "shared-meeting.wav"
    db.commit()

    own_response = user_client.get("/history/uploads")
    all_search_response = user_client.get("/history/uploads?scope=all&q=shared")

    assert own_response.status_code == 200
    assert "seminar.mp4" in own_response.text
    assert "shared-meeting.wav" not in own_response.text
    assert all_search_response.status_code == 200
    assert "shared-meeting.wav" in all_search_response.text
    assert "Guest User" in all_search_response.text


def test_history_all_scope_shows_all_users_without_search(user_client, db, regular_user):
    own_job = _completed_job(db, regular_user.id)
    own_job.audio_file.original_filename = "own-upload.wav"
    other = _other_user(db)
    other_job = _completed_job(db, other.id)
    other_job.audio_file.original_filename = "other-upload.wav"
    db.commit()

    own_response = user_client.get("/history/uploads")
    all_response = user_client.get("/history/uploads?scope=all")

    assert own_response.status_code == 200
    assert "own-upload.wav" in own_response.text
    assert "other-upload.wav" not in own_response.text
    assert all_response.status_code == 200
    assert "own-upload.wav" in all_response.text
    assert "other-upload.wav" in all_response.text
    assert "Guest User" in all_response.text


def test_job_detail_shows_transcription_chunks_with_time_badges(user_client, db, regular_user):
    job = _completed_job(db, regular_user.id)
    db.add_all(
        [
            TranscriptionChunk(
                transcription_job_id=job.id,
                user_id=regular_user.id,
                chunk_index=0,
                start_seconds=0.0,
                end_seconds=10.0,
                raw_text="文字起こしチャンク1",
                refinement_status=ChunkRefinementStatus.COMPLETED,
            ),
            TranscriptionChunk(
                transcription_job_id=job.id,
                user_id=regular_user.id,
                chunk_index=1,
                start_seconds=10.0,
                end_seconds=20.0,
                raw_text="文字起こしチャンク2",
                refinement_status=ChunkRefinementStatus.COMPLETED,
            ),
        ]
    )
    db.commit()

    response = user_client.get(f"/transcription/job/{job.id}")

    assert response.status_code == 200
    assert "00:00:00 - 00:00:10" in response.text
    assert "00:00:10 - 00:00:20" in response.text
    assert "Chunk 01" not in response.text
    assert "文字起こしチャンク1" in response.text
    assert "[00:00:00-00:00:10]" not in response.text


def test_llm_processing_progress_partial_shows_independent_status(user_client, db, regular_user):
    template = PromptTemplate(
        name="文字起こし整形",
        system_prompt="system",
        user_prompt_template="{text}",
        is_active=True,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    job = _completed_job(db, regular_user.id)
    summary = Summary(
        transcription_job_id=job.id,
        user_id=regular_user.id,
        status=SummaryStatus.PROCESSING,
        prompt_template_id=template.id,
        model_name="test-model",
    )
    db.add(summary)
    db.commit()

    response = user_client.get(f"/transcription/job/{job.id}/llm-processing-progress")

    assert response.status_code == 200
    assert "LLM処理" in response.text
    assert "文字起こし整形" in response.text
    assert "LLMに文字起こしを渡して処理しています" in response.text


def test_llm_processing_progress_shows_incremental_refined_chunks(user_client, db, regular_user):
    job = _completed_job(db, regular_user.id)
    db.add_all(
        [
            TranscriptionChunk(
                transcription_job_id=job.id,
                user_id=regular_user.id,
                chunk_index=0,
                start_seconds=0.0,
                end_seconds=10.0,
                raw_text="生チャンク1",
                refined_text="整形済みチャンク1",
                refinement_status=ChunkRefinementStatus.COMPLETED,
            ),
            TranscriptionChunk(
                transcription_job_id=job.id,
                user_id=regular_user.id,
                chunk_index=1,
                start_seconds=10.0,
                end_seconds=20.0,
                raw_text="生チャンク2",
                refinement_status=ChunkRefinementStatus.PROCESSING,
            ),
        ]
    )
    db.commit()

    response = user_client.get(f"/transcription/job/{job.id}/llm-processing-progress")

    assert response.status_code == 200
    assert "整形済み本文" in response.text
    assert "完了した区間から順に表示しています" in response.text
    assert "1 / 2 区間" in response.text
    assert "整形済みチャンク1" in response.text
    assert "00:00:00 - 00:00:10" in response.text
    assert "生チャンク2" not in response.text
    assert "progressive-refined-text" in response.text
    assert 'data-preserve-scroll="progressive-refined-chunks"' in response.text


def test_llm_processing_progress_partial_shows_completed_result(user_client, db, regular_user):
    job = _completed_job(db, regular_user.id)
    summary = Summary(
        transcription_job_id=job.id,
        user_id=regular_user.id,
        status=SummaryStatus.COMPLETED,
        result_text="## 整形結果\n本文です",
        model_name="test-model",
        created_at=datetime(2026, 4, 27, 12, 5, 34, tzinfo=timezone.utc),
        started_at=datetime(2026, 4, 27, 12, 10, 21, tzinfo=timezone.utc),
        completed_at=datetime(2026, 4, 27, 12, 10, 32, tzinfo=timezone.utc),
    )
    db.add(summary)
    db.commit()

    response = user_client.get(f"/transcription/job/{job.id}/llm-processing-progress")

    assert response.status_code == 200
    assert "## 整形結果" in response.text
    assert "summary-result-text" in response.text
    assert "全文ページ" not in response.text
    assert "全文を表示" in response.text
    assert "js-open-llm-result" in response.text
    assert "data-llm-result-source" in response.text
    assert "data-summary-model=\"test-model\"" in response.text
    assert "data-summary-duration=" in response.text
    assert "処理詳細" not in response.text
    assert "data-processing-details" not in response.text
    assert "11.0秒" in response.text
    assert "data-llm-active=\"false\"" in response.text
    assert "hx-get=" not in response.text
    assert "hx-trigger=" not in response.text
    assert "line-clamp" not in response.text


def test_llm_processing_progress_uses_chunk_refinement_timing(user_client, db, regular_user):
    job = _completed_job(db, regular_user.id)
    summary = Summary(
        transcription_job_id=job.id,
        user_id=regular_user.id,
        status=SummaryStatus.COMPLETED,
        result_text="整形済みチャンク1\n\n整形済みチャンク2",
        model_name="test-model",
        created_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc),
        started_at=datetime(2026, 4, 27, 12, 30, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 4, 27, 12, 31, 0, tzinfo=timezone.utc),
        token_usage={"source": "chunk_refinement", "finish_reason": "assembled"},
    )
    db.add_all(
        [
            summary,
            TranscriptionChunk(
                transcription_job_id=job.id,
                user_id=regular_user.id,
                chunk_index=0,
                start_seconds=0.0,
                end_seconds=10.0,
                raw_text="生チャンク1",
                refined_text="整形済みチャンク1",
                refinement_status=ChunkRefinementStatus.COMPLETED,
                refinement_started_at=datetime(2026, 4, 27, 12, 5, 0, tzinfo=timezone.utc),
                refinement_completed_at=datetime(2026, 4, 27, 12, 5, 30, tzinfo=timezone.utc),
            ),
            TranscriptionChunk(
                transcription_job_id=job.id,
                user_id=regular_user.id,
                chunk_index=1,
                start_seconds=10.0,
                end_seconds=20.0,
                raw_text="生チャンク2",
                refined_text="整形済みチャンク2",
                refinement_status=ChunkRefinementStatus.COMPLETED,
                refinement_started_at=datetime(2026, 4, 27, 12, 6, 0, tzinfo=timezone.utc),
                refinement_completed_at=datetime(2026, 4, 27, 12, 7, 0, tzinfo=timezone.utc),
            ),
        ]
    )
    db.commit()

    response = user_client.get(f"/transcription/job/{job.id}/llm-processing-progress")

    assert response.status_code == 200
    assert "2分00秒" in response.text
    assert "data-summary-started=\"2026-04-27 21:05:00\"" in response.text
    assert "data-summary-completed=\"2026-04-27 21:07:00\"" in response.text
    assert "data-summary-duration=\"2分00秒\"" in response.text


def test_llm_processing_progress_warns_when_output_hits_token_limit(user_client, db, regular_user):
    job = _completed_job(db, regular_user.id)
    summary = Summary(
        transcription_job_id=job.id,
        user_id=regular_user.id,
        status=SummaryStatus.COMPLETED,
        result_text="文の途中で",
        model_name="test-model",
        token_usage={"finish_reason": "length", "truncated": True},
    )
    db.add(summary)
    db.commit()

    response = user_client.get(f"/transcription/job/{job.id}/llm-processing-progress")

    assert response.status_code == 200
    assert "結果が途中で切れている可能性があります" in response.text


def test_llm_processing_progress_shows_chunk_timecodes_outside_text(user_client, db, regular_user):
    job = _completed_job(db, regular_user.id)
    summary = Summary(
        transcription_job_id=job.id,
        user_id=regular_user.id,
        status=SummaryStatus.COMPLETED,
        result_text="整形済みチャンク1\n\n整形済みチャンク2",
        model_name="test-model",
        token_usage={"source": "chunk_refinement", "finish_reason": "assembled"},
    )
    db.add_all(
        [
            summary,
            TranscriptionChunk(
                transcription_job_id=job.id,
                user_id=regular_user.id,
                chunk_index=0,
                start_seconds=0.0,
                end_seconds=10.0,
                raw_text="生チャンク1",
                refined_text="整形済みチャンク1",
                refinement_status=ChunkRefinementStatus.COMPLETED,
            ),
            TranscriptionChunk(
                transcription_job_id=job.id,
                user_id=regular_user.id,
                chunk_index=1,
                start_seconds=10.0,
                end_seconds=20.0,
                raw_text="生チャンク2",
                refined_text="整形済みチャンク2",
                refinement_status=ChunkRefinementStatus.COMPLETED,
            ),
        ]
    )
    db.commit()

    response = user_client.get(f"/transcription/job/{job.id}/llm-processing-progress")

    assert response.status_code == 200
    assert "data-llm-rich-source=" in response.text
    assert "summary-result-rich" in response.text
    assert "00:00:00 - 00:00:10" in response.text
    assert "[00:00:00-00:00:10]" not in response.text


def test_llm_processing_progress_strips_timecodes_from_preview(user_client, db, regular_user):
    job = _completed_job(db, regular_user.id)
    summary = Summary(
        transcription_job_id=job.id,
        user_id=regular_user.id,
        status=SummaryStatus.COMPLETED,
        result_text="[00:00:00-00:05:00] 整形済みチャンク1\n\n00:05:00 - 00:10:00 整形済みチャンク2",
        model_name="test-model",
    )
    db.add(summary)
    db.commit()

    response = user_client.get(f"/transcription/job/{job.id}/llm-processing-progress")

    assert response.status_code == 200
    assert "[00:00:00-00:05:00]" in response.text
    match = re.search(r'<div class="[^"]*" data-summary-preview>\s*(.*?)\s*</div>', response.text, re.S)
    assert match
    preview_text = match.group(1)
    assert preview_text.startswith("整形済みチャンク1")
    assert "整形済みチャンク1" in preview_text
    assert "整形済みチャンク2" in preview_text
    assert "00:00:00" not in preview_text
    assert "00:05:00" not in preview_text


def test_llm_processing_progress_can_pause_polling_for_result_panel(user_client, db, regular_user):
    job = _completed_job(db, regular_user.id)
    completed_summary = Summary(
        transcription_job_id=job.id,
        user_id=regular_user.id,
        status=SummaryStatus.COMPLETED,
        result_text="完了済みの長いLLM結果",
        model_name="test-model",
    )
    pending_summary = Summary(
        transcription_job_id=job.id,
        user_id=regular_user.id,
        status=SummaryStatus.PENDING,
        model_name="test-model",
    )
    db.add_all([completed_summary, pending_summary])
    db.commit()

    response = user_client.get(f"/transcription/job/{job.id}/llm-processing-progress")

    assert response.status_code == 200
    assert "data-llm-active=\"true\"" in response.text
    assert "data-polling-paused=\"false\"" in response.text
    assert "hx-trigger=\"every 2s\"" in response.text
    assert "hx-swap=\"outerHTML show:none\"" in response.text
    assert "load, every 2s" not in response.text
    assert "this.dataset" not in response.text
    assert "js-open-llm-result" in response.text
    assert "data-llm-result-source" in response.text
    assert "全文を表示" in response.text


def test_download_transcription_result_formats(user_client, db, regular_user):
    job = _completed_job(db, regular_user.id)

    txt_response = user_client.get(f"/transcription/job/{job.id}/download/txt")
    vtt_response = user_client.get(f"/transcription/job/{job.id}/download/vtt")
    json_response = user_client.get(f"/transcription/job/{job.id}/download/json")

    assert txt_response.status_code == 200
    assert "こんにちは 続き" in txt_response.text
    assert "attachment;" in txt_response.headers["content-disposition"]
    assert vtt_response.status_code == 200
    assert "WEBVTT" in vtt_response.text
    assert "SPEAKER_00: こんにちは" in vtt_response.text
    assert json_response.status_code == 200
    assert '"speaker_blocks"' in json_response.text


def test_stream_job_audio_returns_retained_source_file(user_client, db, regular_user, tmp_path):
    job = _completed_job(db, regular_user.id)
    _make_source_file(db, job, tmp_path)

    response = user_client.get(f"/transcription/job/{job.id}/audio")

    assert response.status_code == 200
    assert response.content == b"audio-bytes"
    assert response.headers["content-type"].startswith("audio/wav")
    assert "inline" in response.headers["content-disposition"]
    assert "source.wav" in response.headers["content-disposition"]


def test_stream_job_audio_returns_404_after_source_file_is_gone(user_client, db, regular_user):
    job = _completed_job(db, regular_user.id)

    response = user_client.get(f"/transcription/job/{job.id}/audio")

    assert response.status_code == 404


def test_stream_job_audio_returns_404_after_retention_expires(user_client, db, regular_user, tmp_path):
    job = _completed_job(db, regular_user.id)
    _make_source_file(db, job, tmp_path)
    job.audio_file.expires_at = utc_now() - timedelta(minutes=1)
    db.commit()

    audio_response = user_client.get(f"/transcription/job/{job.id}/audio")
    detail_response = user_client.get(f"/transcription/job/{job.id}")

    assert audio_response.status_code == 404
    assert 'id="source-media"' not in detail_response.text


def test_download_summary_result(user_client, db, regular_user):
    job = _completed_job(db, regular_user.id)
    summary = Summary(
        transcription_job_id=job.id,
        user_id=regular_user.id,
        status=SummaryStatus.COMPLETED,
        result_text="# 概要\n本文",
        model_name="test-model",
    )
    db.add(summary)
    db.commit()
    db.refresh(summary)

    response = user_client.get(f"/summary/job/{summary.id}/download/md")

    assert response.status_code == 200
    assert response.text == "# 概要\n本文"
    assert "llm.md" in response.headers["content-disposition"]


def test_summary_detail_renders_result_without_javascript(user_client, db, regular_user):
    job = _completed_job(db, regular_user.id)
    summary = Summary(
        transcription_job_id=job.id,
        user_id=regular_user.id,
        status=SummaryStatus.COMPLETED,
        result_text="# 長いLLM処理結果\n\n本文がサーバー描画で見える",
        model_name="test-model",
    )
    db.add(summary)
    db.commit()
    db.refresh(summary)

    response = user_client.get(f"/summary/job/{summary.id}")

    assert response.status_code == 200
    assert "summary-body" in response.text
    assert "# 長いLLM処理結果" in response.text
    assert "本文がサーバー描画で見える" in response.text
    assert "LLM処理結果の全文を表示" in response.text
    assert "次の操作" not in response.text
    assert 'id="summary-progress"' not in response.text
