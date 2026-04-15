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
| `APP_PORT` | 8000 | HTTP port for main app |
| `CHECKER_PORT` | 8001 | HTTP port for checker demo |
| `HTTPS_PORT` | 443 | HTTPS port for main app (with nginx overlay) |
| `CHECKER_HTTPS_PORT` | 8444 | HTTPS port for checker demo (with nginx overlay) |

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
