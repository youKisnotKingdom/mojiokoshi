# Mojiokoshi

Audio transcription and summarization web application for on-premises deployment.

## Features

- File upload transcription as the primary production path
- Optional browser recording with real-time transcription (feature flag)
- File upload support (MP3, WAV, M4A, FLAC, OGG, WebM, etc.)
- Batch transcription using Parakeet JA by default with faster-whisper fallback
- LLM-powered summarization via local OpenAI-compatible API
- Multi-user support with admin/user roles
- Automatic audio file cleanup

## Tech Stack

- **Backend**: FastAPI (Python)
- **Frontend**: HTMX + Jinja2 + Tailwind CSS
- **Database**: PostgreSQL
- **Background Worker**: In-process polling worker
- **Transcription**: Parakeet JA (NeMo) / faster-whisper fallback
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
LLM_MAX_TOKENS=8192
LLM_TIMEOUT=300

# Batch transcription defaults
DEFAULT_TRANSCRIPTION_ENGINE=parakeet_ja
WORKER_WHISPER_DEVICE=cuda
ENABLE_REALTIME_TRANSCRIPTION=false
PARAKEET_CHUNK_SECONDS=300
AUDIO_PREPROCESSING_MODE=light
MAX_UPLOAD_SIZE=1073741824
NGINX_CLIENT_MAX_BODY_SIZE=1g

# Optional fallback/checker settings
WHISPER_MODEL_SIZE=medium
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
- **worker**: Background worker for batch transcription and summarization
- **db**: PostgreSQL database
- **checker**: Real-time transcription checker demo — `http://<server-ip>:8001`

With HTTPS overlay (`docker-compose.https.yml`):
- Main app: https://\<server-ip\> (port 443)
- Checker demo: https://\<server-ip\>:8444 (HTTPS required for microphone access)

Production defaults:
- Batch transcription runs on the `worker` container with `Parakeet JA`
- `web` stays on CPU by default so batch and UI do not compete for GPU
- Real-time recording UI is disabled by default with `ENABLE_REALTIME_TRANSCRIPTION=false`
- The checker demo is optional and should stay on CPU unless you are explicitly testing it

Recommended production profile:
- Normal operation: `worker=1`, `PARAKEET_CHUNK_SECONDS=300`
- Burst handling: scale to `worker=2` before changing chunk size
- Do not treat `worker=3` as a normal setting on this `16GB` GPU
- Keep other GPU-heavy services such as `open-webui` off the same host or stopped during batch-heavy periods

### OpenLDAP Authentication

This app does not run an LDAP server. Point `LDAP_SERVER_URI` at an existing
OpenLDAP server on the internal network.

Local 6-digit users remain available. When OpenLDAP is enabled, users can log in
with their LDAP ID; the app creates a linked local user on first successful login
so existing ownership, history, and permissions continue to use the internal user
table.

```env
LDAP_ENABLED=true
LDAP_SERVER_URI=ldap://ldap.example.local:389
LDAP_BIND_DN=cn=readonly,dc=example,dc=local
LDAP_BIND_PASSWORD=...
LDAP_USER_BASE_DN=ou=people,dc=example,dc=local
LDAP_USER_FILTER=(uid={username})
LDAP_USER_ID_ATTRIBUTE=uid
LDAP_DISPLAY_NAME_ATTRIBUTE=cn
LDAP_START_TLS=false
LDAP_DEFAULT_ROLE=user
```

Optional admin group mapping:

```env
LDAP_GROUP_BASE_DN=ou=groups,dc=example,dc=local
LDAP_GROUP_FILTER=(member={user_dn})
LDAP_ADMIN_GROUP_DN=cn=mojiokoshi-admins,ou=groups,dc=example,dc=local
```

If LDAP is disabled, the login screen only accepts the existing 6-digit user ID.
If LDAP is enabled, the same field accepts either a local 6-digit user ID or an
LDAP ID.

### Offline Speaker Diarization Model

Speaker diarization is designed for offline deployment, but the `pyannote` model
itself should be prepared once on a connected machine and then mounted into the app.

Speaker diarization is kept as an optional post-processing path. It is disabled
for normal operation because it consumes GPU/CPU time, can delay queued work, and
its labels are not always accurate enough to justify running it for every file.

Normal production settings:

```env
ENABLE_SPEAKER_DIARIZATION=false
```

When speaker labels are explicitly needed, enable the feature and start the
dedicated profile:

```env
ENABLE_SPEAKER_DIARIZATION=true
SPEAKER_DIARIZATION_MODEL_PATH=/app/models/pyannote/speaker-diarization-community-1
SPEAKER_DIARIZATION_DEVICE=auto
DIARIZATION_WORKER_CONCURRENCY=1
HUGGINGFACE_TOKEN=
```

```bash
docker compose --profile diarization up -d diarization-worker
```

Speaker diarization runs as a post-ASR job. The plain transcript is completed first
and can be used by LLM processing immediately; speaker labels are attached later by
`diarization-worker`. This avoids blocking the main transcription result at `99%`
for long recordings and keeps LLM result provenance clear.

Preparation flow:

1. Accept the model conditions for `pyannote/speaker-diarization-community-1` on Hugging Face.
2. Use an access token on a connected machine and download the model into your shared models directory.
3. Mount that directory into the application so the runtime never needs internet access.

Helper script:

```bash
# Use either `uvx hf auth login` / `hf auth login` or an explicit token.
# export HUGGINGFACE_TOKEN=...
python3 scripts/download_speaker_diarization_model.py \
  --output-dir /path/to/models/pyannote/speaker-diarization-community-1
```

Then mount it into Docker, for example via the existing models volume or a host path, and set:

```env
SPEAKER_DIARIZATION_MODEL_PATH=/app/models/pyannote/speaker-diarization-community-1
```

At runtime, if `SPEAKER_DIARIZATION_MODEL_PATH` exists, the app does not fetch from Hugging Face.

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | - | Secret key for session signing (required) |
| `ALLOWED_HOSTS` | localhost,127.0.0.1,::1 | Comma-separated allowed `Host` headers |
| `DATABASE_URL` | - | PostgreSQL connection URL |
| `LLM_API_BASE_URL` | - | Local LLM server URL |
| `LLM_MODEL_NAME` | default | Model name for summarization |
| `LLM_MAX_TOKENS` | 8192 | Max output tokens for final LLM processing |
| `LLM_TIMEOUT` | 300 | LLM request timeout in seconds |
| `DEFAULT_TRANSCRIPTION_ENGINE` | parakeet_ja | Default batch transcription engine |
| `AUDIO_PREPROCESSING_MODE` | light | ASR input preprocessing: `off`, `light`, or `denoise` |
| `WHISPER_MODEL_SIZE` | medium | faster-whisper fallback / checker model size |
| `WEB_WHISPER_DEVICE` | cpu | Device used by `web` in Docker |
| `WORKER_WHISPER_DEVICE` | cuda | Device used by batch worker in Docker |
| `CHECKER_WHISPER_DEVICE` | cpu | Device used by checker demo in Docker |
| `ENABLE_REALTIME_TRANSCRIPTION` | false | Show browser recording UI |
| `WORKER_TRANSCRIPTION_CONCURRENCY` | 1 | Claimed transcription jobs per worker process |
| `WORKER_CHUNK_REFINEMENT_CONCURRENCY` | 1 | Claimed chunk-level LLM refinement jobs per worker process |
| `WORKER_SUMMARY_CONCURRENCY` | 1 | Claimed summary jobs per worker process |
| `ENABLE_CHUNK_LLM_REFINEMENT` | true | Persist ASR chunks and clean up each chunk with the LLM before final LLM processing |
| `LLM_CHUNK_REFINEMENT_MAX_INPUT_CHARS` | 12000 | Max characters sent to the LLM for one ASR chunk |
| `LLM_CHUNK_REFINEMENT_MAX_OUTPUT_TOKENS` | 2000 | Max output tokens for one chunk refinement |
| `LLM_CHUNK_REFINEMENT_CONTEXT_CHARS` | 1000 | Previous chunk context characters included for continuity |
| `LLM_WORKER_CHUNK_REFINEMENT_CONCURRENCY` | 2 | Chunk refinement concurrency for the `llm-worker` service |
| `LLM_WORKER_SUMMARY_CONCURRENCY` | 1 | Final LLM processing concurrency for the `llm-worker` service |
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

### Runtime Notes

- The current app runtime does **not** use vLLM request batching for transcription.
- Batch jobs are claimed from PostgreSQL by the worker process and executed one job at a time per worker process.
- Real-time recording remains a separate, optional path and is disabled by default in production.

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
