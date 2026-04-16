#!/usr/bin/env python3
"""
YouTube から取得した評価データを既存ベンチマークへ流すラッパ
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT / "benchmark_data"
BENCHMARK_SCRIPT = ROOT / "scripts" / "benchmark_asr.py"


def find_audio(video_id: str) -> Path:
    matches = sorted((DATA_ROOT / "audio").glob(f"{video_id}.*"))
    if not matches:
        raise SystemExit(f"音声ファイルが見つかりません: {video_id}")
    return matches[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YouTube 音声データの ASR ベンチマーク")
    parser.add_argument("--video-id", required=True, help="YouTube 動画 ID")
    parser.add_argument("--models", nargs="+", required=True, help="比較するモデル alias")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--chunk-seconds", type=int, default=300)
    parser.add_argument("--faster-whisper-size", default="medium")
    parser.add_argument("--qwen-max-new-tokens", type=int, default=4096)
    parser.add_argument("--qwen-max-inference-batch-size", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audio_path = find_audio(args.video_id)
    gold_reference_path = DATA_ROOT / "reference_gold" / f"{args.video_id}.txt"
    fallback_reference_path = DATA_ROOT / "reference" / f"{args.video_id}.txt"
    reference_path = gold_reference_path if gold_reference_path.exists() else fallback_reference_path

    command = [
        sys.executable,
        str(BENCHMARK_SCRIPT),
        "--audio",
        str(audio_path),
        "--models",
        *args.models,
        "--device",
        args.device,
        "--language",
        args.language,
        "--chunk-seconds",
        str(args.chunk_seconds),
        "--faster-whisper-size",
        args.faster_whisper_size,
        "--qwen-max-new-tokens",
        str(args.qwen_max_new_tokens),
        "--qwen-max-inference-batch-size",
        str(args.qwen_max_inference_batch_size),
    ]

    if reference_path.exists():
        command.extend(["--reference", str(reference_path)])

    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
