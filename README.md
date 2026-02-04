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
docker-compose -f docker-compose.dev.yml up -d
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

6. Open http://localhost:8000

### Development CSS Watch

```bash
npm run watch:css
```

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
├── uploads/              # Uploaded files
├── tests/                # Test files
├── tasks/                # Project task management
├── docker-compose.dev.yml
├── requirements.txt
└── package.json
```

## License

MIT
