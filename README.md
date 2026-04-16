# Mojiokoshi

Audio transcription and summarization web application for on-premises deployment.

## Features

- Browser-based audio recording with real-time transcription
- File upload support (MP3, WAV, M4A, FLAC, OGG, WebM, etc.)
- Streaming transcription using Whisper/faster-whisper
- LLM-powered summarization via local OpenAI-compatible API
- Multi-user support with admin/user roles
- Automatic audio file cleanup

## Tech Stack

- **Backend**: FastAPI (Python)
- **Frontend**: HTMX + Jinja2 + Tailwind CSS
- **Database**: PostgreSQL
- **Task Queue**: Celery + Redis
- **Transcription**: Whisper / faster-whisper (GPU)
- **Summarization**: Local LLM server (vLLM, Ollama, etc.)

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 18+ (for Tailwind CSS build)
- Docker & Docker Compose

### Quick Start

1. Clone the repository and install dependencies:

```bash
# Create virtual environment
python -m venv .venv

source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate  # Windows

# Install Python dependencies
pip install -r requirements.txt

# If you use uv
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt

# Install Node dependencies and build CSS
npm install
npm run build:css
```

2. Download HTMX (for offline use):

```bash
curl -o static/js/htmx.min.js https://unpkg.com/htmx.org@1.9.10/dist/htmx.min.js
```

3. Start development services:

```bash
docker compose -f docker-compose.dev.yml up -d
```

4. Set up environment:

```bash
cp .env.example .env
# Edit .env as needed
```

5. Run the development server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

6. Open `http://localhost:8000` for local development

### Development CSS Watch

```bash
npm run watch:css
```

## Production Deployment (Docker)

### Prerequisites

- Docker & Docker Compose
- NVIDIA GPU with CUDA support (for transcription)
- Local LLM server (vLLM, Ollama, llama.cpp, etc.)

### Quick Deploy

1. Clone and configure:

```bash
git clone <repository>
cd mojiokoshi
cp .env.example .env
```

2. Edit `.env` with your settings:

```bash
# Required: Set a secure secret key
SECRET_KEY=your-secure-secret-key-here

# Hosts allowed in the Host header
ALLOWED_HOSTS=localhost,127.0.0.1,<server-ip>

# LLM server on your local network
LLM_API_BASE_URL=http://<llm-server-ip>:8080/v1
LLM_MODEL_NAME=your-model-name

# Whisper settings
WHISPER_MODEL_SIZE=large
WHISPER_DEVICE=cuda  # or 'cpu' for CPU-only
```

3. Build and start:

```bash
docker compose up -d --build
```

4. Create admin user:

```bash
docker compose exec web python scripts/init_db.py --create-admin --admin-id 000001
```

5. Access at `http://<server-ip>:8000`

### GPU Support

For NVIDIA GPU support, ensure you have:
- NVIDIA Container Toolkit installed
- NVIDIA driver installed on the host

### Services

The deployment includes:
- **web**: Main web application (FastAPI) — `http://<server-ip>:8000`
- **worker**: Background worker for transcription and summarization
- **db**: PostgreSQL database
- **checker**: Real-time transcription checker demo — `http://<server-ip>:8001`

With HTTPS overlay (`docker-compose.https.yml`):
- Main app: https://\<server-ip\> (port 443)
- Checker demo: https://\<server-ip\>:8444 (HTTPS required for microphone access)

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | - | Secret key for session signing (required) |
| `ALLOWED_HOSTS` | localhost,127.0.0.1,::1 | Comma-separated allowed `Host` headers |
| `DATABASE_URL` | - | PostgreSQL connection URL |
| `LLM_API_BASE_URL` | - | Local LLM server URL |
| `LLM_MODEL_NAME` | default | Model name for summarization |
| `WHISPER_MODEL_SIZE` | large | Whisper model (tiny/base/small/medium/large) |
| `WHISPER_DEVICE` | cpu | Device for Whisper (cuda/cpu) |
| `AUDIO_RETENTION_DAYS` | 30 | Days to keep audio files |
| `MAX_UPLOAD_SIZE` | 1073741824 | Max upload size in bytes (Docker default: 1GB) |
| `NGINX_CLIENT_MAX_BODY_SIZE` | 1g | nginx upload limit for HTTPS overlay |
| `APP_PORT` | 8000 | HTTP port for main app |
| `CHECKER_PORT` | 8001 | HTTP port for checker demo |
| `HTTPS_PORT` | 443 | HTTPS port for main app (with nginx overlay) |
| `CHECKER_HTTPS_PORT` | 8444 | HTTPS port for checker demo (with nginx overlay) |

### Upload Size Guide

The application code defaults to `500MB`, but the Docker deployment now overrides this to `1GB`.
For long audio, the practical limit is usually file size first, not GPU memory.

Recommended settings:
- `1GB`: practical default for on-prem deployments with hour-scale MP3/M4A
- `2GB`: only if you expect long WAV uploads or high-bitrate recordings

Set both values together:

```env
MAX_UPLOAD_SIZE=1073741824
NGINX_CLIENT_MAX_BODY_SIZE=1g
```

or:

```env
MAX_UPLOAD_SIZE=2147483648
NGINX_CLIENT_MAX_BODY_SIZE=2g
```

Approximate maximum durations:

| Limit | WAV 16kHz 16bit mono | WAV 44.1kHz 16bit stereo | MP3 / M4A 128kbps | MP3 / M4A 256kbps |
|-------|-----------------------|---------------------------|-------------------|-------------------|
| 500MB | 4.55 hours | 0.83 hours | 9.10 hours | 4.55 hours |
| 1GB | 9.10 hours | 1.65 hours | 18.20 hours | 9.10 hours |
| 2GB | 18.20 hours | 3.31 hours | 36.41 hours | 18.20 hours |

Notes:
- For `FLAC`, the file size depends heavily on the source audio, so use the actual file size rather than duration alone.
- With the current benchmarked models and chunked inference (`120s` or `300s` chunks), a `16GB` GPU is sufficient for `1GB` to `2GB` class uploads. The bottleneck is upload size, wall-clock time, and disk usage rather than VRAM.
- In practice, `1GB` is enough for roughly `18 hours` of `128kbps` MP3/M4A or `9 hours` of `16kHz mono WAV`.
- `2GB` is reasonable if you want to accept multi-hour WAV without re-encoding, but beyond that the web upload path becomes the bigger operational risk.

### ASR 検証用モデル

アプリ本体に直接組み込まず、比較検証だけしたいモデルは `config/asr_validation_models.json` と
`scripts/download_validation_models.py` で管理します。

登録済みの候補:
- `nvidia/parakeet-tdt_ctc-0.6b-ja`
- `CohereLabs/cohere-transcribe-03-2026`
- `reazon-research/japanese-zipformer-base-k2-rs35kh`
- `Qwen/Qwen3-ASR-0.6B` (`qwen_asr` の検証対象)

コマンド例:

```bash
# 登録済みモデルを確認
python scripts/download_validation_models.py --list

# すべて取得
python scripts/download_validation_models.py

# Qwen3-ASR だけ取得
python scripts/download_validation_models.py --only qwen_asr
```

`CohereLabs/cohere-transcribe-03-2026` のような gated model を取得する場合は、
Hugging Face 上でアクセス承認後に `HF_TOKEN` を設定してください。

長尺音声の比較検証は `scripts/benchmark_asr.py` を使います。

```bash
python scripts/benchmark_asr.py \
  --audio /path/to/meeting.mp3 \
  --models faster_whisper qwen_asr parakeet_ja reazon_zipformer cohere_transcribe \
  --language ja \
  --device cuda \
  --chunk-seconds 300
```

結果は `benchmarks/<timestamp>/` に保存され、`report.json` に `real_time_factor` と
`x_realtime` が出ます。日本語の長尺比較は、まず `--chunk-seconds 300` で揃えるのが無難です。

### ASR ベンチ用 Docker 環境

比較検証は `Dockerfile.asr-benchmark` を使うと再現しやすく、`HF_HOME=/app/models` にモデルを
集約できるので、そのままオフライン環境へ持っていきやすくなります。

```bash
# ベンチ用イメージをビルド
scripts/run_benchmark_in_docker.sh --build "python --version"

# 検証用モデルを /app/models にダウンロード
scripts/run_benchmark_in_docker.sh \
  "python scripts/download_validation_models.py --only qwen_asr parakeet_ja reazon_zipformer cohere_transcribe"

# オフライン持ち込み時は HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1 を付けて実行
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 scripts/run_benchmark_in_docker.sh \
  \"python scripts/benchmark_youtube_audio.py --video-id BmtnWaUvX_0 --models faster_whisper qwen_asr\"
```

### YouTube 長尺データの取得

公開動画を検証に使う場合は、音声と自動字幕を一緒に取得して `benchmark_data/` に保存できます。
自動字幕は完全な正解ではありませんが、長尺比較の一次評価には使えます。

```bash
# 1本だけ取得
python scripts/download_youtube_audio.py BmtnWaUvX_0

# manifest に登録した 6 本を全部取得
python scripts/download_youtube_audio.py --all

# 取得済みデータで評価
python scripts/benchmark_youtube_audio.py \
  --video-id BmtnWaUvX_0 \
  --models faster_whisper \
  --device cuda \
  --chunk-seconds 300
```

動画 manifest は `config/japanese_longform_youtube_videos.json` にあります。

## Project Structure

```
mojiokoshi/
├── app/
│   ├── main.py           # FastAPI entry point
│   ├── config.py         # Settings
│   ├── database.py       # DB connection
│   ├── models/           # SQLAlchemy models
│   ├── schemas/          # Pydantic schemas
│   ├── routers/          # API routes
│   ├── services/         # Business logic
│   └── templates/        # Jinja2 templates
├── static/
│   ├── css/              # Built CSS
│   ├── js/               # JavaScript (HTMX, etc.)
│   └── src/              # Tailwind source
├── config/               # Validation model catalogs
├── uploads/              # Uploaded files
├── tests/                # Test files
├── tasks/                # Project task management
├── docker-compose.dev.yml
├── requirements.txt
└── package.json
```

## License

MIT
