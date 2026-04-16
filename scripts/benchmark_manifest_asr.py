#!/usr/bin/env python3
"""
manifest.jsonl で与えた短発話集合を、モデルを 1 回だけロードしてまとめて評価する。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from benchmark_asr import (
    DEFAULT_OUTPUT_ROOT,
    build_adapter,
    compute_error_rates,
    ensure_directory,
    get_torch_peak_reserved_mb,
    now_stamp,
    parse_cuda_device_index,
    query_gpu_memory_used_mb,
    reset_torch_peak_memory,
    resolve_device,
    resolve_models,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="manifest ベースの ASR 評価")
    parser.add_argument("--manifest", type=Path, required=True, help="manifest.jsonl")
    parser.add_argument("--dataset-name", required=True, help="結果表示用のデータセット名")
    parser.add_argument("--models", nargs="+", required=True, help="モデル alias")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--limit", type=int, default=None, help="先頭 N 件だけ評価")
    parser.add_argument("--log-every", type=int, default=50, help="進捗ログ間隔")
    parser.add_argument(
        "--faster-whisper-size",
        default="medium",
        help="faster_whisper alias 用のモデルサイズ",
    )
    parser.add_argument(
        "--qwen-max-new-tokens",
        type=int,
        default=2048,
        help="Qwen3-ASR 用の max_new_tokens",
    )
    parser.add_argument(
        "--qwen-max-inference-batch-size",
        type=int,
        default=8,
        help="Qwen3-ASR 用の max_inference_batch_size",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="結果保存先。未指定時は benchmarks/<timestamp>/<dataset_name>",
    )
    return parser.parse_args()


def load_manifest(path: Path, limit: int | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            items.append(json.loads(line))
            if limit is not None and len(items) >= limit:
                break
    if not items:
        raise SystemExit(f"manifest が空です: {path}")
    return items


def maybe_clear_torch_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        return


def benchmark_dataset(
    items: list[dict[str, Any]],
    model: dict[str, Any],
    args: argparse.Namespace,
    device: str,
    output_root: Path,
) -> dict[str, Any]:
    build_adapter.qwen_max_new_tokens = args.qwen_max_new_tokens
    build_adapter.qwen_max_inference_batch_size = args.qwen_max_inference_batch_size
    adapter = build_adapter(
        model_alias=model["alias"],
        repo_id=model["repo_id"],
        family=model.get("family"),
        device=device,
        faster_whisper_size=args.faster_whisper_size,
        language=args.language or None,
    )

    model_output_dir = output_root / model["alias"]
    ensure_directory(model_output_dir)

    device_index = parse_cuda_device_index(device)
    gpu_memory_after_load_mb = query_gpu_memory_used_mb(device_index)
    reset_torch_peak_memory(device_index)

    predictions: list[dict[str, Any]] = []
    reference_parts: list[str] = []
    hypothesis_parts: list[str] = []
    total_audio_s = 0.0
    started_all = time.perf_counter()

    for index, item in enumerate(items, start=1):
        audio_path = Path(item["audio_path"])
        reference_text = item["reference_text"].strip()
        duration_s = float(item.get("duration_s", 0.0))

        started = time.perf_counter()
        hypothesis_text = adapter.transcribe(audio_path, args.language or None).strip()
        wall_time_s = time.perf_counter() - started

        predictions.append(
            {
                "id": item["id"],
                "audio_path": item["audio_path"],
                "duration_s": duration_s,
                "wall_time_s": wall_time_s,
                "reference_text": reference_text,
                "hypothesis_text": hypothesis_text,
            }
        )
        reference_parts.append(reference_text)
        hypothesis_parts.append(hypothesis_text)
        total_audio_s += duration_s

        if index == 1 or index % max(1, args.log_every) == 0 or index == len(items):
            print(
                f"[{args.dataset_name}:{model['alias']}] "
                f"item={index}/{len(items)} audio={duration_s:.1f}s wall={wall_time_s:.2f}s"
            )

    total_wall_s = time.perf_counter() - started_all
    combined_reference = "\n".join(reference_parts)
    combined_hypothesis = "\n".join(hypothesis_parts)
    metrics = compute_error_rates(combined_reference, combined_hypothesis)
    report = {
        "dataset_name": args.dataset_name,
        "model_alias": model["alias"],
        "repo_id": model["repo_id"],
        "num_items": len(items),
        "total_audio_s": total_audio_s,
        "total_wall_s": total_wall_s,
        "real_time_factor": total_wall_s / total_audio_s if total_audio_s > 0 else None,
        "x_realtime": total_audio_s / total_wall_s if total_wall_s > 0 else None,
        "reference_metrics": metrics,
        "gpu_memory_after_load_mb": gpu_memory_after_load_mb,
        "gpu_memory_after_run_mb": query_gpu_memory_used_mb(device_index),
        "torch_peak_reserved_mb": get_torch_peak_reserved_mb(device_index),
    }

    with (model_output_dir / "predictions.jsonl").open("w", encoding="utf-8") as handle:
        for row in predictions:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (model_output_dir / "reference.txt").write_text(f"{combined_reference}\n", encoding="utf-8")
    (model_output_dir / "hypothesis.txt").write_text(f"{combined_hypothesis}\n", encoding="utf-8")
    (model_output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    del adapter
    maybe_clear_torch_cache()
    return report


def main() -> None:
    args = parse_args()
    items = load_manifest(args.manifest, args.limit)
    device = resolve_device(args.device)
    output_root = args.output_dir or (DEFAULT_OUTPUT_ROOT / now_stamp() / args.dataset_name)
    ensure_directory(output_root)

    reports: list[dict[str, Any]] = []
    for model in resolve_models(args.models):
        reports.append(
            benchmark_dataset(
                items=items,
                model=model,
                args=args,
                device=device,
                output_root=output_root,
            )
        )

    (output_root / "summary.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"完了: {output_root}")
    for report in reports:
        cer = None
        if report["reference_metrics"]:
            cer = report["reference_metrics"].get("cer")
        cer_str = f"{cer * 100:.2f}%" if isinstance(cer, (int, float)) else "n/a"
        print(
            f"- {report['model_alias']}: items={report['num_items']} "
            f"xRealtime={report['x_realtime']:.2f} CER={cer_str}"
        )


if __name__ == "__main__":
    main()
