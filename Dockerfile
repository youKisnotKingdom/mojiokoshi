# Multi-stage build for Mojiokoshi
# Stage 1: Build Tailwind CSS
FROM node:20-slim AS tailwind-builder

WORKDIR /build

COPY package.json ./
RUN npm install

COPY tailwind.config.js ./
COPY static/src/input.css ./static/src/
COPY app/templates ./app/templates/

RUN npx tailwindcss -i ./static/src/input.css -o ./static/css/styles.css --minify


# Stage 2: Main application
FROM python:3.11-slim

# Install system dependencies (ffmpeg for audio processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (includes faster-whisper)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app ./app
COPY demo ./demo
COPY alembic ./alembic
COPY alembic.ini .
COPY scripts ./scripts
COPY static ./static

# Copy built CSS from tailwind stage
COPY --from=tailwind-builder /build/static/css/styles.css ./static/css/styles.css

# Create upload directory
RUN mkdir -p /app/uploads

RUN chmod +x scripts/entrypoint.sh

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
# Whisper/HuggingFace モデルキャッシュをボリュームに向ける
ENV HF_HOME=/app/models

EXPOSE 8000

ENTRYPOINT ["scripts/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
