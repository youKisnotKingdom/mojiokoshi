#!/usr/bin/env bash
set -euo pipefail

IMAGE_TAG="${ASR_BENCHMARK_IMAGE:-mojiokoshi-asr-benchmark:latest}"
BUILD_IMAGE=0

if [[ "${1:-}" == "--build" ]]; then
  BUILD_IMAGE=1
  shift
fi

if [[ $# -eq 0 ]]; then
  echo "Usage: scripts/run_benchmark_in_docker.sh [--build] '<command>'" >&2
  exit 1
fi

if [[ "${BUILD_IMAGE}" -eq 1 ]]; then
  docker build -f Dockerfile.asr-benchmark -t "${IMAGE_TAG}" .
fi

HF_CACHE_DIR="${HOME}/.cache/huggingface"
HF_CACHE_MOUNT=()
if [[ -d "${HF_CACHE_DIR}" ]]; then
  HF_CACHE_MOUNT=(-v "${HF_CACHE_DIR}:/root/.cache/huggingface")
fi

docker run --rm \
  --entrypoint /bin/bash \
  --gpus all \
  -e HF_HOME=/app/models \
  -e TRANSFORMERS_CACHE=/app/models \
  -e HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-0}" \
  -e TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-0}" \
  -v "$(pwd):/app" \
  -v mojiokoshi_models:/app/models \
  "${HF_CACHE_MOUNT[@]}" \
  -w /app \
  "${IMAGE_TAG}" \
  -lc "$*"
