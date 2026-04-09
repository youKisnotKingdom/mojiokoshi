"""
ストリーミング・音声アップロードの統合テスト

- TestAudioUpload : 合成WAVをアップロードしてジョブが作られることを確認
- TestCheckerWebSocket : PCMチャンクを逐次送り、逐次的にtranscriptが返ることを確認
"""
import io
import json
import struct
import time
import math
import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession


# ---------------------------------------------------------------------------
# 音声ユーティリティ
# ---------------------------------------------------------------------------

def make_silence_wav(duration_sec: float = 1.0, sample_rate: int = 16000) -> bytes:
    """無音の WAV バイト列を生成する"""
    num_samples = int(sample_rate * duration_sec)
    pcm = b'\x00' * (num_samples * 2)  # 16-bit mono
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + len(pcm), b'WAVE',
        b'fmt ', 16, 1, 1,
        sample_rate, sample_rate * 2, 2, 16,
        b'data', len(pcm),
    )
    return header + pcm


def make_tone_pcm(duration_sec: float = 3.0, sample_rate: int = 16000,
                  freq: float = 440.0) -> bytes:
    """サイン波の PCM バイト列（Int16 mono）を生成する"""
    num_samples = int(sample_rate * duration_sec)
    samples = []
    for i in range(num_samples):
        val = int(32767 * 0.3 * math.sin(2 * math.pi * freq * i / sample_rate))
        samples.append(val)
    return struct.pack(f'<{num_samples}h', *samples)


def make_tone_wav(duration_sec: float = 1.0, sample_rate: int = 16000) -> bytes:
    pcm = make_tone_pcm(duration_sec, sample_rate)
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + len(pcm), b'WAVE',
        b'fmt ', 16, 1, 1,
        sample_rate, sample_rate * 2, 2, 16,
        b'data', len(pcm),
    )
    return header + pcm


# ---------------------------------------------------------------------------
# 音声アップロードテスト（メインアプリ）
# ---------------------------------------------------------------------------

class TestAudioUpload:
    """音声ファイルアップロード → ジョブ作成の確認"""

    def test_wav_upload_creates_job(self, user_client):
        """WAV ファイルをアップロードすると文字起こしジョブが作成される"""
        import re
        csrf_resp = user_client.get("/transcription/upload")
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', csrf_resp.text)
        csrf = csrf_match.group(1) if csrf_match else ""

        wav = make_tone_wav(duration_sec=1.0)
        response = user_client.post(
            "/transcription/upload",
            data={"engine": "faster_whisper", "model_size": "small", "csrf_token": csrf},
            files={"file": ("test.wav", io.BytesIO(wav), "audio/wav")},
        )
        assert response.status_code == 200, response.text
        # ジョブ詳細ページにリダイレクト or 直接表示
        assert "文字起こし" in response.text or "job" in response.url

    def test_mp3_upload_accepted(self, user_client):
        """mp3 拡張子のファイルも受け付ける"""
        import re
        csrf_resp = user_client.get("/transcription/upload")
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', csrf_resp.text)
        csrf = csrf_match.group(1) if csrf_match else ""

        # 中身は WAV だが拡張子 mp3 で送る（形式チェックは拡張子ベース）
        wav = make_silence_wav(0.5)
        response = user_client.post(
            "/transcription/upload",
            data={"engine": "faster_whisper", "model_size": "small", "csrf_token": csrf},
            files={"file": ("test.mp3", io.BytesIO(wav), "audio/mpeg")},
        )
        assert response.status_code == 200, response.text

    def test_txt_upload_rejected(self, user_client):
        """テキストファイルは 400 で拒否される"""
        import re
        csrf_resp = user_client.get("/transcription/upload")
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', csrf_resp.text)
        csrf = csrf_match.group(1) if csrf_match else ""

        response = user_client.post(
            "/transcription/upload",
            data={"engine": "faster_whisper", "model_size": "small", "csrf_token": csrf},
            files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# WebSocket ストリーミングテスト（チェッカーデモ）
# ---------------------------------------------------------------------------

DUMMY_TRANSCRIPT_CHUNKS = [
    "プロジェクトの目的についてお話しします。",
    "スケジュールは来月末を予定しています。",
    "担当者は田中さんと佐藤さんです。",
]


@pytest.fixture
def checker_client():
    """チェッカーアプリの TestClient"""
    # Whisper と LLM をモックしてテスト
    from demo.checker import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestCheckerWebSocket:
    """チェッカーの WebSocket ストリーミング動作確認"""

    def test_websocket_connects(self, checker_client):
        """WebSocket に接続できる"""
        with checker_client.websocket_connect("/ws") as ws:
            # 接続成功（例外なし）
            pass

    def test_topics_message_accepted(self, checker_client):
        """topics メッセージを送っても切断されない"""
        with checker_client.websocket_connect("/ws") as ws:
            ws.send_json({
                "type": "topics",
                "topics": ["目的の説明", "スケジュール", "担当者確認"],
            })
            # エラーが返らなければOK（タイムアウト前に切断されない）

    def test_pcm_chunks_trigger_transcripts(self, checker_client):
        """PCM バイナリを送ると transcript メッセージが逐次返ってくる"""
        chunk_texts = iter(DUMMY_TRANSCRIPT_CHUNKS)

        def mock_transcribe(pcm_bytes):
            try:
                return next(chunk_texts)
            except StopIteration:
                return ""

        with patch("demo.checker.transcribe_pcm", side_effect=mock_transcribe):
            with checker_client.websocket_connect("/ws") as ws:
                ws.send_json({
                    "type": "topics",
                    "topics": ["目的の説明", "スケジュール", "担当者確認"],
                })

                received_transcripts = []
                # BYTES_PER_CHUNK (96000 bytes) 分のPCMを3回送る
                chunk_size = 96000
                pcm_chunk = make_tone_pcm(duration_sec=3.0)  # ちょうど96000bytes

                for _ in range(3):
                    ws.send_bytes(pcm_chunk)
                    msg = ws.receive_json()
                    assert msg["type"] == "transcript", f"expected transcript, got {msg}"
                    assert msg["new_text"], "transcript text should not be empty"
                    received_transcripts.append(msg["new_text"])

                # 3チャンク分が逐次返ってきていること
                assert len(received_transcripts) == 3
                assert received_transcripts[0] == DUMMY_TRANSCRIPT_CHUNKS[0]
                assert received_transcripts[1] == DUMMY_TRANSCRIPT_CHUNKS[1]
                assert received_transcripts[2] == DUMMY_TRANSCRIPT_CHUNKS[2]

    def test_coverage_message_sent_after_enough_text(self, checker_client):
        """十分なテキストが溜まると coverage メッセージが送られる"""
        call_count = 0

        def mock_transcribe(pcm_bytes):
            nonlocal call_count
            call_count += 1
            return "プロジェクトの目的についてスケジュールと担当者を説明します。" * 3

        async def mock_check_coverage(transcript, topics):
            return [0, 1, 2]  # 全項目カバー済みを返す

        with patch("demo.checker.transcribe_pcm", side_effect=mock_transcribe), \
             patch("demo.checker.check_coverage", side_effect=mock_check_coverage):

            with checker_client.websocket_connect("/ws") as ws:
                ws.send_json({
                    "type": "topics",
                    "topics": ["目的の説明", "スケジュール", "担当者確認"],
                })

                pcm_chunk = make_tone_pcm(duration_sec=3.0)
                ws.send_bytes(pcm_chunk)

                messages = []
                # transcript と coverage の両方を受け取る
                for _ in range(2):
                    try:
                        msg = ws.receive_json()
                        messages.append(msg)
                    except Exception:
                        break

                types = {m["type"] for m in messages}
                assert "transcript" in types
                assert "coverage" in types

                coverage_msg = next(m for m in messages if m["type"] == "coverage")
                assert set(coverage_msg["covered"]) == {0, 1, 2}

    def test_flush_processes_remaining_buffer(self, checker_client):
        """flush メッセージで残バッファが処理される"""
        transcribed = []

        def mock_transcribe(pcm_bytes):
            transcribed.append(len(pcm_bytes))
            return "残りのバッファを処理しました。"

        with patch("demo.checker.transcribe_pcm", side_effect=mock_transcribe):
            with checker_client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "topics", "topics": ["テスト項目"]})

                # BYTES_PER_CHUNK より小さいデータを送る（バッファに溜まるだけ）
                small_chunk = make_tone_pcm(duration_sec=1.0)  # 32000 bytes < 96000
                ws.send_bytes(small_chunk)

                # flush を送ると処理される
                ws.send_json({"type": "flush"})
                msg = ws.receive_json()
                assert msg["type"] == "transcript"
                assert "残りのバッファ" in msg["new_text"]
