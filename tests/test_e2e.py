"""
E2E 統合テスト（実際のWhisperモデル + 実際のLLM使用）

実行方法:
    pytest tests/test_e2e.py -v -s \
        --whisper-model=tiny \
        --llm-url=http://<llm-server-ip>:7801/v1 \
        --llm-model=qwen3.5-35b-awq-a5000-14

マーカー: @pytest.mark.e2e
通常の pytest tests/ では除外されます（--run-e2e フラグが必要）
"""
import io
import os
import struct
import wave
from pathlib import Path
from unittest.mock import patch

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TEST_AUDIO_WAV = FIXTURES_DIR / "test_speech_ja.wav"
TEST_AUDIO_MP3 = FIXTURES_DIR / "test_speech_ja.mp3"

# E2E テスト用の設定（環境変数またはデフォルト値）
WHISPER_MODEL = os.environ.get("WHISPER_MODEL_SIZE", "tiny")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
LLM_URL = os.environ.get("LLM_API_BASE_URL")
LLM_MODEL = os.environ.get("LLM_MODEL_NAME", "qwen3.5-35b-awq-a5000-14")


def require_llm_config() -> tuple[str, str]:
    if not LLM_URL:
        pytest.skip("LLM_API_BASE_URL is not set")
    return LLM_URL, LLM_MODEL




# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def read_wav_as_pcm(wav_path: Path) -> bytes:
    """WAV ファイルから PCM バイト列を読み込む"""
    with wave.open(str(wav_path), "rb") as wf:
        return wf.readframes(wf.getnframes())


def split_pcm_chunks(pcm: bytes, chunk_sec: float = 3.0,
                     sample_rate: int = 16000) -> list[bytes]:
    """PCM を指定秒数のチャンクに分割"""
    chunk_size = int(sample_rate * chunk_sec * 2)  # 16bit mono
    return [pcm[i:i + chunk_size] for i in range(0, len(pcm), chunk_size)]


# ---------------------------------------------------------------------------
# E2E テスト: Whisper 単体
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestWhisperE2E:
    def test_transcribe_real_audio(self, request):
        """実際の Whisper モデルで日本語音声を文字起こしできる"""
        model_size = WHISPER_MODEL

        assert TEST_AUDIO_WAV.exists(), f"テスト音声が見つかりません: {TEST_AUDIO_WAV}"

        from faster_whisper import WhisperModel
        compute_type = "float16" if WHISPER_DEVICE == "cuda" else "int8"
        print(f"\nWhisper モデルをロード中: {model_size} on {WHISPER_DEVICE}")
        model = WhisperModel(model_size, device=WHISPER_DEVICE, compute_type=compute_type)

        print("文字起こし中...")
        segments, info = model.transcribe(
            str(TEST_AUDIO_WAV),
            beam_size=3,
            vad_filter=True,
        )
        text = "".join(s.text for s in segments).strip()

        print(f"\n検出言語: {info.language} (確率: {info.language_probability:.2f})")
        print(f"文字起こし結果:\n{text}")

        assert text, "文字起こし結果が空です"
        assert info.language == "ja", f"日本語を期待しましたが {info.language} でした"

        # 主要キーワードが含まれているか確認
        keywords = ["プロジェクト", "目的", "スケジュール"]
        found = [kw for kw in keywords if kw in text]
        print(f"\nキーワード検出: {found} / {keywords}")
        assert len(found) >= 2, f"キーワードが少なすぎます: {found}"


# ---------------------------------------------------------------------------
# E2E テスト: LLM 単体
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestLLME2E:
    def test_llm_reachable(self, request):
        """LLM API に接続できて応答が返る"""
        import httpx
        llm_url, _ = require_llm_config()

        resp = httpx.get(f"{llm_url}/models", timeout=5.0)
        assert resp.status_code == 200
        print(f"\nLLM モデル一覧: {[m['id'] for m in resp.json().get('data', [])]}")

    def test_llm_coverage_check(self, request):
        """LLM がカバレッジチェックを正しく返す"""
        import asyncio
        import sys
        sys.path.insert(0, ".")

        llm_url, llm_model = require_llm_config()

        os.environ["LLM_API_BASE_URL"] = llm_url
        os.environ["LLM_MODEL_NAME"] = llm_model

        from demo.checker import check_coverage

        transcript = (
            "本日はプロジェクトの目的についてご説明します。"
            "スケジュールは来月末を予定しています。"
            "担当者は田中さんです。"
        )
        topics = ["プロジェクトの目的", "スケジュール", "担当者確認", "リスクと対策"]

        print(f"\nトピック: {topics}")
        print(f"文字起こし: {transcript}")

        covered = asyncio.run(check_coverage(transcript, topics))
        print(f"カバー済み (0-indexed): {covered}")
        print(f"カバー済みトピック: {[topics[i] for i in covered]}")

        assert len(covered) >= 2, f"少なくとも2項目カバーされるべきです: {covered}"
        assert 0 in covered, "「プロジェクトの目的」がカバーされていません"
        assert 1 in covered, "「スケジュール」がカバーされていません"


# ---------------------------------------------------------------------------
# E2E テスト: チェッカー WebSocket（実Whisper + 実LLM）
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestCheckerE2E:
    def test_full_pipeline(self, request):
        """実音声 → Whisper → LLM カバレッジチェック の全パイプライン"""
        import asyncio
        import sys
        sys.path.insert(0, ".")

        model_size = WHISPER_MODEL
        llm_url, llm_model = require_llm_config()

        os.environ["WHISPER_MODEL_SIZE"] = model_size
        os.environ["WHISPER_DEVICE"] = WHISPER_DEVICE
        os.environ["LLM_API_BASE_URL"] = llm_url
        os.environ["LLM_MODEL_NAME"] = llm_model

        assert TEST_AUDIO_WAV.exists()
        pcm = read_wav_as_pcm(TEST_AUDIO_WAV)
        chunks = split_pcm_chunks(pcm, chunk_sec=3.0)
        print(f"\n音声チャンク数: {len(chunks)}")

        from demo.checker import transcribe_pcm, check_coverage

        topics = ["プロジェクトの目的", "スケジュール", "担当者確認", "リスクと対策"]

        # Whisper で全チャンクを文字起こし
        print("文字起こし中...")
        full_text = ""
        for i, chunk in enumerate(chunks):
            if len(chunk) < 16000:  # 0.5秒未満はスキップ
                continue
            text = transcribe_pcm(chunk)
            if text:
                full_text += text + " "
                print(f"  チャンク{i+1}: {text[:50]}...")

        print(f"\n全文:\n{full_text.strip()}")
        assert full_text.strip(), "文字起こし結果が空です"

        # LLM でカバレッジチェック
        print("\nLLM でカバレッジ確認中...")
        covered = asyncio.run(check_coverage(full_text.strip(), topics))
        print(f"カバー済み: {[topics[i] for i in covered]}")
        print(f"未カバー: {[topics[i] for i in range(len(topics)) if i not in covered]}")

        assert len(covered) >= 2, f"少なくとも2項目はカバーされるべきです: {covered}"

    def test_websocket_with_real_audio(self, request):
        """WebSocket 経由で実音声を送り、transcript と coverage が返ることを確認"""
        import sys
        sys.path.insert(0, ".")

        model_size = WHISPER_MODEL
        llm_url, llm_model = require_llm_config()

        os.environ["WHISPER_MODEL_SIZE"] = model_size
        os.environ["WHISPER_DEVICE"] = WHISPER_DEVICE
        os.environ["LLM_API_BASE_URL"] = llm_url
        os.environ["LLM_MODEL_NAME"] = llm_model

        # モデルキャッシュをリセット
        import demo.checker as checker_module
        checker_module._whisper_model = None

        from demo.checker import app
        from fastapi.testclient import TestClient

        assert TEST_AUDIO_WAV.exists()
        pcm = read_wav_as_pcm(TEST_AUDIO_WAV)
        chunks = split_pcm_chunks(pcm, chunk_sec=3.0)

        topics = ["プロジェクトの目的", "スケジュール", "担当者確認"]

        received = {"transcripts": [], "coverages": []}

        import threading

        received = {"transcripts": [], "coverages": []}
        done = threading.Event()

        def receive_loop(ws):
            """バックグラウンドで受信し続けるスレッド"""
            while not done.is_set():
                try:
                    msg = ws.receive_json()
                    if msg["type"] == "transcript":
                        received["transcripts"].append(msg["new_text"])
                        print(f" transcript: {msg['new_text'][:40]}...")
                    elif msg["type"] == "coverage":
                        received["coverages"].append(msg["covered"])
                        print(f" coverage: {msg['covered']}")
                except Exception:
                    break

        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "topics", "topics": topics})

                # 受信スレッドを先に起動
                recv_thread = threading.Thread(target=receive_loop, args=(ws,), daemon=True)
                recv_thread.start()

                print(f"\n{len(chunks)} チャンクを送信中...")
                for i, chunk in enumerate(chunks):
                    if len(chunk) < 16000:
                        continue
                    ws.send_bytes(chunk)
                    print(f"  チャンク {i+1}/{len(chunks)} 送信済み")

                ws.send_json({"type": "flush"})

                # flush 後の処理を待つ（最大60秒）
                recv_thread.join(timeout=60)
                done.set()

        print(f"\n受信した transcript 数: {len(received['transcripts'])}")
        print(f"カバレッジ更新回数: {len(received['coverages'])}")

        assert len(received["transcripts"]) > 0, "transcript が1件も受信できませんでした"
