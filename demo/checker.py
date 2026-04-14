"""
文字起こしチェッカー デモアプリ

話す内容のチェックリストを事前に入力しておくと、
リアルタイム文字起こしの中でカバーされた項目が自動でチェックされていく。

起動方法:
  uvicorn demo.checker:app --port 8001

環境変数:
  WHISPER_MODEL_SIZE  モデルサイズ (default: small)
  WHISPER_DEVICE      cpu / cuda (default: cpu)
  LLM_API_BASE_URL    OpenAI互換API URL (required)
  LLM_MODEL_NAME      使用モデル名 (default: default)
"""
import asyncio
import json
import logging
import os
import re
import struct
import tempfile
from pathlib import Path

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "medium")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "ja")
LLM_API_BASE_URL = os.environ.get("LLM_API_BASE_URL")
if not LLM_API_BASE_URL:
    raise RuntimeError("LLM_API_BASE_URL must be set for demo.checker")
LLM_MODEL_NAME = os.environ.get("LLM_MODEL_NAME", "default")

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2
# 音声バッファがこのサイズ（秒）を超えたら文字起こし実行
TRANSCRIBE_INTERVAL_SEC = 3
BYTES_PER_CHUNK = SAMPLE_RATE * BYTES_PER_SAMPLE * TRANSCRIBE_INTERVAL_SEC  # 96000 bytes

# LLM チェックは新規テキストがこの文字数以上増えたときに実行
LLM_CHECK_THRESHOLD = 40

_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        compute_type = "float16" if WHISPER_DEVICE == "cuda" else "int8"
        logger.info("Whisper モデルをロード中: %s on %s", WHISPER_MODEL_SIZE, WHISPER_DEVICE)
        _whisper_model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=compute_type,
        )
        logger.info("Whisper モデルのロード完了")
    return _whisper_model


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Raw PCM (Int16 mono) → WAV バイト列に変換"""
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm_bytes), b"WAVE",
        b"fmt ", 16, 1, 1,
        sample_rate, sample_rate * BYTES_PER_SAMPLE, BYTES_PER_SAMPLE, 16,
        b"data", len(pcm_bytes),
    )
    return header + pcm_bytes


def transcribe_pcm(pcm_bytes: bytes) -> str:
    """PCM バイト列を文字起こしして結果テキストを返す"""
    wav = pcm_to_wav(pcm_bytes)
    model = get_whisper_model()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav)
        tmp_path = f.name
    try:
        segments, info = model.transcribe(
            tmp_path,
            language=WHISPER_LANGUAGE,
            beam_size=3,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        text = "".join(s.text for s in segments).strip()
        if text:
            logger.info("文字起こし: %r (lang=%s)", text[:60], info.language)
        return text
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def check_coverage(transcript: str, topics: list[str]) -> list[int]:
    """
    LLM に問い合わせて、transcript の中でカバーされたトピックの
    0-indexed リストを返す。LLM が使えない場合は空リスト。
    """
    if not transcript.strip() or not topics:
        return []

    topics_text = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(topics))
    prompt = (
        "以下のチェックリストと会話の文字起こしを照合してください。\n\n"
        f"チェックリスト:\n{topics_text}\n\n"
        f"文字起こし:\n{transcript}\n\n"
        "文字起こしの中で言及・説明・確認されたチェック項目の番号を "
        'JSONで返してください。形式: {"covered": [1, 3]}\n'
        "触れられていない項目は含めないでください。JSONのみ返してください。"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{LLM_API_BASE_URL}/chat/completions",
                json={
                    "model": LLM_MODEL_NAME,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 150,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        match = re.search(r'"covered"\s*:\s*\[([^\]]*)\]', content)
        if match:
            nums = [int(x.strip()) for x in match.group(1).split(",") if x.strip().isdigit()]
            covered = [n - 1 for n in nums if 1 <= n <= len(topics)]
            logger.info("LLM カバレッジ: %s", covered)
            return covered
    except Exception as e:
        logger.warning("LLM チェック失敗 (スキップ): %s", e)
    return []


app = FastAPI(title="文字起こしチェッカー")


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket 接続")

    topics: list[str] = []
    full_transcript = ""
    covered: set[int] = set()
    pcm_buffer = bytearray()
    last_check_len = 0

    try:
        while True:
            msg = await websocket.receive()

            # ---- テキストメッセージ（制御コマンド） ----
            if "text" in msg:
                data = json.loads(msg["text"])

                if data["type"] == "topics":
                    topics = [t.strip() for t in data["topics"] if t.strip()]
                    full_transcript = ""
                    covered = set()
                    pcm_buffer = bytearray()
                    last_check_len = 0
                    logger.info("トピック設定: %s", topics)

                elif data["type"] == "flush":
                    # 録音停止時に残バッファを処理
                    if len(pcm_buffer) > SAMPLE_RATE * BYTES_PER_SAMPLE // 2:  # 0.5秒以上
                        await _process_buffer(
                            websocket, bytes(pcm_buffer),
                            topics, full_transcript, covered, last_check_len
                        )
                    pcm_buffer = bytearray()

            # ---- バイナリメッセージ（PCM 音声データ） ----
            elif "bytes" in msg:
                pcm_buffer.extend(msg["bytes"])

                if len(pcm_buffer) >= BYTES_PER_CHUNK:
                    buf = bytes(pcm_buffer)
                    pcm_buffer = bytearray()

                    result = await _process_buffer(
                        websocket, buf,
                        topics, full_transcript, covered, last_check_len
                    )
                    if result:
                        full_transcript, covered, last_check_len = result

    except WebSocketDisconnect:
        logger.info("WebSocket 切断")
    except Exception as e:
        logger.error("WebSocket エラー: %s", e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


async def _process_buffer(
    websocket: WebSocket,
    pcm_bytes: bytes,
    topics: list[str],
    full_transcript: str,
    covered: set[int],
    last_check_len: int,
) -> tuple[str, set[int], int] | None:
    """PCM バッファを文字起こし → LLM チェック → クライアントに送信"""
    loop = asyncio.get_event_loop()
    new_text = await loop.run_in_executor(None, transcribe_pcm, pcm_bytes)

    if not new_text:
        return None

    full_transcript = full_transcript + new_text + " "
    await websocket.send_json({
        "type": "transcript",
        "new_text": new_text,
        "full_text": full_transcript.strip(),
    })

    # 十分な新規テキストが溜まったら LLM でカバレッジ確認
    if topics and (len(full_transcript) - last_check_len) >= LLM_CHECK_THRESHOLD:
        last_check_len = len(full_transcript)
        new_covered_list = await check_coverage(full_transcript.strip(), topics)
        prev_covered = set(covered)
        covered.update(new_covered_list)
        if covered != prev_covered:
            await websocket.send_json({
                "type": "coverage",
                "covered": list(covered),
                "total": len(topics),
            })

    return full_transcript, covered, last_check_len


# ---------------------------------------------------------------------------
# フロントエンド HTML（インライン）
# ---------------------------------------------------------------------------
HTML = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>文字起こしチェッカー</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic UI", sans-serif;
  background: #f0f2f5;
  color: #1a1a2e;
  min-height: 100vh;
}
.header {
  background: white;
  border-bottom: 1px solid #e5e7eb;
  padding: 16px 24px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.header h1 { font-size: 1.2rem; font-weight: 700; }
.header p { font-size: 0.85rem; color: #6b7280; margin-top: 2px; }
.main { max-width: 1100px; margin: 0 auto; padding: 24px; display: grid; grid-template-columns: 340px 1fr; gap: 20px; }
@media (max-width: 720px) { .main { grid-template-columns: 1fr; } }
.card { background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden; }
.card-header { padding: 16px 20px; border-bottom: 1px solid #f3f4f6; }
.card-header h2 { font-size: 0.95rem; font-weight: 600; color: #374151; }
.card-body { padding: 20px; }

/* 左パネル */
.topics-textarea {
  width: 100%; border: 1px solid #d1d5db; border-radius: 8px; padding: 10px 12px;
  font-size: 0.9rem; line-height: 1.6; resize: vertical; outline: none;
  font-family: inherit; color: #374151;
}
.topics-textarea:focus { border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,0.1); }
.btn-group { display: flex; gap: 8px; margin-top: 12px; }
.btn {
  flex: 1; padding: 10px; border: none; border-radius: 8px;
  font-size: 0.9rem; font-weight: 600; cursor: pointer; transition: all 0.15s;
}
.btn-primary { background: #6366f1; color: white; }
.btn-primary:hover { background: #4f46e5; }
.btn-primary.active { background: #ef4444; }
.btn-primary.active:hover { background: #dc2626; }
.btn-primary:disabled { background: #9ca3af; cursor: not-allowed; }
.btn-secondary { background: #f3f4f6; color: #4b5563; }
.btn-secondary:hover { background: #e5e7eb; }

/* 進捗バー */
.progress-wrap { margin-top: 20px; }
.progress-label { display: flex; justify-content: space-between; font-size: 0.8rem; color: #6b7280; margin-bottom: 6px; }
.progress-track { height: 8px; background: #e5e7eb; border-radius: 4px; overflow: hidden; }
.progress-fill { height: 100%; background: linear-gradient(90deg, #6366f1, #8b5cf6); border-radius: 4px; transition: width 0.5s ease; }

/* チェックリスト */
.checklist { list-style: none; margin-top: 16px; display: flex; flex-direction: column; gap: 4px; }
.check-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 8px;
  transition: all 0.3s ease; font-size: 0.9rem;
}
.check-item.pending { background: #fafafa; color: #374151; }
.check-item.covered { background: #f0fdf4; color: #6b7280; }
.check-icon {
  width: 22px; height: 22px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.3s ease;
}
.check-item.pending .check-icon { border: 2px solid #d1d5db; }
.check-item.covered .check-icon { background: #22c55e; border: 2px solid #22c55e; color: white; }
.check-label { flex: 1; }
.check-item.covered .check-label { text-decoration: line-through; }
.empty-hint { font-size: 0.85rem; color: #9ca3af; font-style: italic; padding: 8px 0; }

/* 右パネル */
.right-panel { display: flex; flex-direction: column; gap: 20px; }
.transcript-box {
  min-height: 200px; max-height: 360px; overflow-y: auto;
  background: #fafafa; border: 1px solid #e5e7eb; border-radius: 8px;
  padding: 14px 16px; font-size: 0.95rem; line-height: 1.8; color: #374151;
}
.transcript-box .new { color: #6366f1; font-weight: 500; }
.transcript-placeholder { color: #9ca3af; font-style: italic; }

/* ステータスバー */
.status-bar {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 16px; background: #f9fafb; border-radius: 8px;
  font-size: 0.85rem; color: #6b7280;
}
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #d1d5db; flex-shrink: 0; }
.status-dot.recording { background: #ef4444; animation: blink 1.2s ease-in-out infinite; }
.status-dot.connected { background: #22c55e; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }

/* 完了バナー */
.complete-banner {
  display: none; background: #f0fdf4; border: 1px solid #bbf7d0;
  border-radius: 10px; padding: 16px 20px; text-align: center;
}
.complete-banner.show { display: block; }
.complete-banner .icon { font-size: 2rem; margin-bottom: 8px; }
.complete-banner p { color: #166534; font-weight: 600; font-size: 1rem; }
.complete-banner small { color: #4ade80; font-size: 0.85rem; }
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>文字起こしチェッカー</h1>
    <p>話しながら、チェックリストの項目が自動で消化されていきます</p>
  </div>
</div>

<div class="main">
  <!-- 左パネル：チェックリスト設定 -->
  <div>
    <div class="card">
      <div class="card-header"><h2>話す内容リスト</h2></div>
      <div class="card-body">
        <textarea id="topicsInput" class="topics-textarea" rows="7"
          placeholder="1行1項目で入力&#10;&#10;例:&#10;自己紹介・役割の説明&#10;プロジェクトの背景と目的&#10;現状の課題&#10;提案する解決策&#10;スケジュールと担当&#10;質疑応答"></textarea>
        <div class="btn-group">
          <button id="startBtn" class="btn btn-primary">録音開始</button>
          <button id="resetBtn" class="btn btn-secondary">リセット</button>
        </div>

        <div class="progress-wrap" id="progressWrap" style="display:none;">
          <div class="progress-label">
            <span>進捗</span>
            <span id="progressText">0 / 0 項目</span>
          </div>
          <div class="progress-track">
            <div class="progress-fill" id="progressFill" style="width:0%"></div>
          </div>
        </div>

        <ul class="checklist" id="checklist">
          <li><p class="empty-hint">上のテキストエリアに項目を入力してください</p></li>
        </ul>
      </div>
    </div>
  </div>

  <!-- 右パネル：文字起こし -->
  <div class="right-panel">
    <div class="card" id="completeBannerCard" style="display:none;">
      <div class="card-body">
        <div class="complete-banner show" id="completeBanner">
          <div class="icon">✅</div>
          <p>すべての項目をカバーしました！</p>
          <small>お疲れ様でした</small>
        </div>
      </div>
    </div>

    <div class="card" style="flex:1;">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;">
        <h2>リアルタイム文字起こし</h2>
        <div class="status-bar" style="padding:6px 10px;font-size:0.8rem;">
          <div class="status-dot" id="statusDot"></div>
          <span id="statusText">待機中</span>
        </div>
      </div>
      <div class="card-body">
        <div class="transcript-box" id="transcriptBox">
          <span class="transcript-placeholder">録音を開始すると文字起こしが表示されます</span>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
const SAMPLE_RATE = 16000;

let ws = null;
let audioCtx = null;
let processor = null;
let source = null;
let mediaStream = null;
let recording = false;
let topics = [];
let covered = new Set();

const startBtn = document.getElementById('startBtn');
const resetBtn = document.getElementById('resetBtn');
const topicsInput = document.getElementById('topicsInput');
const checklist = document.getElementById('checklist');
const transcriptBox = document.getElementById('transcriptBox');
const progressFill = document.getElementById('progressFill');
const progressText = document.getElementById('progressText');
const progressWrap = document.getElementById('progressWrap');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const completeBannerCard = document.getElementById('completeBannerCard');

function parseTopics() {
  return topicsInput.value.split('\n').map(s => s.trim()).filter(Boolean);
}

function renderChecklist() {
  if (topics.length === 0) {
    checklist.innerHTML = '<li><p class="empty-hint">上のテキストエリアに項目を入力してください</p></li>';
    progressWrap.style.display = 'none';
    completeBannerCard.style.display = 'none';
    return;
  }
  progressWrap.style.display = 'block';
  checklist.innerHTML = topics.map((t, i) => {
    const done = covered.has(i);
    return `<li class="check-item ${done ? 'covered' : 'pending'}">
      <div class="check-icon">
        ${done ? '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="1,6 4,10 11,2"/></svg>' : ''}
      </div>
      <span class="check-label">${escHtml(t)}</span>
    </li>`;
  }).join('');

  const pct = topics.length > 0 ? Math.round(covered.size / topics.length * 100) : 0;
  progressFill.style.width = pct + '%';
  progressText.textContent = `${covered.size} / ${topics.length} 項目`;

  if (topics.length > 0 && covered.size === topics.length) {
    completeBannerCard.style.display = 'block';
  } else {
    completeBannerCard.style.display = 'none';
  }
}

function appendTranscript(text) {
  const placeholder = transcriptBox.querySelector('.transcript-placeholder');
  if (placeholder) placeholder.remove();

  const span = document.createElement('span');
  span.className = 'new';
  span.textContent = text + ' ';
  transcriptBox.appendChild(span);
  transcriptBox.scrollTop = transcriptBox.scrollHeight;

  setTimeout(() => span.className = '', 2500);
}

function setStatus(text, mode) {
  statusText.textContent = text;
  statusDot.className = 'status-dot' + (mode ? ' ' + mode : '');
}

function openWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => setStatus('接続済み', 'connected');
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'transcript') {
      appendTranscript(msg.new_text);
    } else if (msg.type === 'coverage') {
      covered = new Set(msg.covered);
      renderChecklist();
    } else if (msg.type === 'error') {
      setStatus('エラー: ' + msg.message, '');
    }
  };
  ws.onclose = () => {
    if (recording) stopRecording();
    setStatus('切断', '');
  };
  ws.onerror = () => setStatus('接続エラー', '');
}

async function startRecording() {
  topics = parseTopics();
  if (topics.length === 0) {
    alert('話す内容リストに少なくとも1項目入力してください');
    return;
  }

  covered = new Set();
  renderChecklist();
  transcriptBox.innerHTML = '';
  completeBannerCard.style.display = 'none';

  openWS();
  // WS が open になるまで待つ
  await new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error('WS タイムアウト')), 5000);
    ws.addEventListener('open', () => { clearTimeout(t); resolve(); }, { once: true });
    ws.addEventListener('error', () => { clearTimeout(t); reject(new Error('WS エラー')); }, { once: true });
  }).catch(err => { alert(err.message); return Promise.reject(err); });

  ws.send(JSON.stringify({ type: 'topics', topics }));

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { sampleRate: SAMPLE_RATE, channelCount: 1, echoCancellation: true, noiseSuppression: true }
    });
    audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: SAMPLE_RATE });
    source = audioCtx.createMediaStreamSource(mediaStream);
    processor = audioCtx.createScriptProcessor(4096, 1, 1);

    processor.onaudioprocess = (e) => {
      if (!recording || ws?.readyState !== WebSocket.OPEN) return;
      const float32 = e.inputBuffer.getChannelData(0);
      const int16 = new Int16Array(float32.length);
      for (let i = 0; i < float32.length; i++) {
        int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32767));
      }
      ws.send(int16.buffer);
    };

    source.connect(processor);
    processor.connect(audioCtx.destination);

    recording = true;
    startBtn.textContent = '録音停止';
    startBtn.classList.add('active');
    topicsInput.disabled = true;
    setStatus('録音中...', 'recording');

  } catch (err) {
    alert('マイクへのアクセスが拒否されました: ' + err.message);
    ws?.close();
  }
}

function stopRecording() {
  recording = false;

  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'flush' }));
    setTimeout(() => ws?.close(), 1500);
  }

  processor?.disconnect();
  source?.disconnect();
  mediaStream?.getTracks().forEach(t => t.stop());
  audioCtx?.close();
  processor = source = mediaStream = audioCtx = null;

  startBtn.textContent = '録音開始';
  startBtn.classList.remove('active');
  topicsInput.disabled = false;
  setStatus('停止', '');
}

function reset() {
  if (recording) stopRecording();
  ws?.close();
  ws = null;
  covered = new Set();
  topics = parseTopics();
  renderChecklist();
  transcriptBox.innerHTML = '<span class="transcript-placeholder">録音を開始すると文字起こしが表示されます</span>';
  completeBannerCard.style.display = 'none';
  setStatus('待機中', '');
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

startBtn.addEventListener('click', () => { recording ? stopRecording() : startRecording(); });
resetBtn.addEventListener('click', reset);

// 初期描画
topics = parseTopics();
renderChecklist();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
