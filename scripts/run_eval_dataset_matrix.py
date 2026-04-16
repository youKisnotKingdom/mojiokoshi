#!/usr/bin/env python3
"""
準備済み manifest を使って短発話データセットの評価を順番に回す。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET_ROOT = ROOT / "benchmark_datasets"
BENCHMARK_SCRIPT = ROOT / "scripts" / "benchmark_manifest_asr.py"
DEFAULT_OUTPUT_ROOT = ROOT / "benchmarks" / "dataset_matrix"

MODEL_CONFIGS = {
    "faster_whisper": ["--faster-whisper-size", "medium"],
    "qwen_asr": ["--qwen-max-new-tokens", "2048"],
    "qwen_asr_1_7b": ["--qwen-max-new-tokens", "2048", "--qwen-max-inference-batch-size", "4"],
    "cohere_transcribe": [],
    "reazon_zipformer": [],
    "reazon_hubert_k2": [],
    "reazon_nemo_v2": [],
    "parakeet_ja": [],
    "canary_1b_flash": [],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="manifest ベースの ASR データセット評価を一括実行")
    parser.add_argument("--datasets", nargs="+", required=True, help="dataset alias")
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


def dataset_manifest_path(dataset_name: str) -> Path:
    manifest_path = DATASET_ROOT / dataset_name / "manifest.jsonl"
    if not manifest_path.exists():
        raise SystemExit(f"manifest が見つかりません: {manifest_path}")
    return manifest_path


def run_one(dataset_name: str, model_alias: str, args: argparse.Namespace) -> None:
    manifest_path = dataset_manifest_path(dataset_name)
    model_output_dir = args.output_root / dataset_name / model_alias
    report_path = model_output_dir / model_alias / "report.json"
    if args.skip_existing and report_path.exists():
        print(f"[skip] {dataset_name} {model_alias}")
        return

    command = [
        sys.executable,
        str(BENCHMARK_SCRIPT),
        "--manifest",
        str(manifest_path),
        "--dataset-name",
        dataset_name,
        "--models",
        model_alias,
        "--device",
        args.device,
        "--language",
        args.language,
        "--output-dir",
        str(model_output_dir),
        *MODEL_CONFIGS[model_alias],
    ]
    print(f"[run] {dataset_name} {model_alias}")
    subprocess.run(command, check=True)


def main() -> None:
    args = parse_args()
    for dataset_name in args.datasets:
        for model_alias in args.models:
            run_one(dataset_name, model_alias, args)


if __name__ == "__main__":
    main()
