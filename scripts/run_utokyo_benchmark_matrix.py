#!/usr/bin/env python3
"""
東大講義ベンチマークをモデルごとに順番に回す runner

例:
  python scripts/run_utokyo_benchmark_matrix.py --all
  python scripts/run_utokyo_benchmark_matrix.py --video-ids BmtnWaUvX_0 jkUMzOFAVV4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "config" / "japanese_longform_youtube_videos.json"
BENCHMARK_SCRIPT = ROOT / "scripts" / "benchmark_asr.py"
DATA_ROOT = ROOT / "benchmark_data"
DEFAULT_OUTPUT_ROOT = ROOT / "benchmarks" / "utokyo_matrix"

MODEL_CONFIGS = {
    "faster_whisper": {
        "chunk_seconds": 300,
        "extra_args": ["--faster-whisper-size", "medium"],
    },
    "qwen_asr": {
        "chunk_seconds": 300,
        "extra_args": ["--qwen-max-new-tokens", "2048"],
    },
    "qwen_asr_1_7b": {
        "chunk_seconds": 300,
        "extra_args": ["--qwen-max-new-tokens", "2048", "--qwen-max-inference-batch-size", "4"],
    },
    "cohere_transcribe": {
        "chunk_seconds": 300,
        "extra_args": [],
    },
    "reazon_zipformer": {
        "chunk_seconds": 120,
        "extra_args": [],
    },
    "reazon_hubert_k2": {
        "chunk_seconds": 120,
        "extra_args": [],
    },
    "reazon_nemo_v2": {
        "chunk_seconds": 120,
        "extra_args": [],
    },
    "parakeet_ja": {
        "chunk_seconds": 300,
        "extra_args": [],
    },
    "canary_1b_flash": {
        "chunk_seconds": 300,
        "extra_args": [],
    },
}


def load_manifest() -> list[dict]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["videos"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="東大講義の ASR ベンチマークを一括実行")
    parser.add_argument("--all", action="store_true", help="manifest の全動画を対象にする")
    parser.add_argument("--video-ids", nargs="*", default=[], help="対象の動画 ID")
    parser.add_argument(
        "--models",
        nargs="+",
        default=list(MODEL_CONFIGS),
        choices=list(MODEL_CONFIGS),
        help="実行するモデル alias",
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def resolve_targets(args: argparse.Namespace) -> list[str]:
    manifest_ids = [item["id"] for item in load_manifest()]
    if args.all:
        return manifest_ids
    if args.video_ids:
        return args.video_ids
    raise SystemExit("`--all` か `--video-ids` のどちらかを指定してください。")


def find_audio(video_id: str) -> Path:
    matches = sorted((DATA_ROOT / "audio").glob(f"{video_id}.*"))
    if not matches:
        raise SystemExit(f"音声ファイルが見つかりません: {video_id}")
    return matches[0]


def find_reference(video_id: str) -> Path | None:
    gold = DATA_ROOT / "reference_gold" / f"{video_id}.txt"
    if gold.exists():
        return gold
    fallback = DATA_ROOT / "reference" / f"{video_id}.txt"
    if fallback.exists():
        return fallback
    return None


def run_one(video_id: str, model_alias: str, args: argparse.Namespace) -> None:
    config = MODEL_CONFIGS[model_alias]
    model_output_root = args.output_root / video_id / model_alias
    report_path = model_output_root / model_alias / "report.json"
    if args.skip_existing and report_path.exists():
        print(f"[skip] {video_id} {model_alias}")
        return

    audio_path = find_audio(video_id)
    reference_path = find_reference(video_id)
    command = [
        sys.executable,
        str(BENCHMARK_SCRIPT),
        "--audio",
        str(audio_path),
        "--models",
        model_alias,
        "--device",
        args.device,
        "--language",
        args.language,
        "--chunk-seconds",
        str(config["chunk_seconds"]),
        "--output-dir",
        str(model_output_root),
        *config["extra_args"],
    ]
    if reference_path:
        command.extend(["--reference", str(reference_path)])

    print(f"[run] {video_id} {model_alias}")
    subprocess.run(command, check=True)


def main() -> None:
    args = parse_args()
    targets = resolve_targets(args)
    for video_id in targets:
        for model_alias in args.models:
            run_one(video_id, model_alias, args)


if __name__ == "__main__":
    main()
