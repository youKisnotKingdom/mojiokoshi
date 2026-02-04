# Multi-stage build for Mojiokoshi
# Stage 1: Build Tailwind CSS
FROM node:20-slim AS tailwind-builder

WORKDIR /build

# Copy package files
COPY package.json package-lock.json* ./
RUN npm ci

# Copy Tailwind config and source
COPY tailwind.config.js ./
COPY static/src/input.css ./static/src/
COPY app/templates ./app/templates/

# Build CSS
RUN npx tailwindcss -i ./static/src/input.css -o ./static/css/styles.css --minify


# Stage 2: Main application
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install faster-whisper with CUDA support (for GPU)
# Note: For CPU-only, use: pip install faster-whisper
RUN pip install --no-cache-dir faster-whisper

# Copy application code
COPY app ./app
COPY scripts ./scripts
COPY static ./static

# Copy built CSS from tailwind stage
COPY --from=tailwind-builder /build/static/css/styles.css ./static/css/styles.css

# Create upload directory
RUN mkdir -p /app/uploads

# Make entrypoint executable
RUN chmod +x scripts/entrypoint.sh

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Entrypoint for database initialization
ENTRYPOINT ["scripts/entrypoint.sh"]

# Default command (can be overridden)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
