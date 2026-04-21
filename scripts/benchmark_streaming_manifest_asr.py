#!/usr/bin/env python3
"""
擬似ストリーミング前提の manifest ベース ASR 評価。

現在のアプリに近い「一定秒数ごとに chunk を送り、その chunk を独立に推論して
結果を順次連結する」方式を比較する。
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from benchmark_asr import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SAMPLE_RATE,
    build_adapter,
    compute_error_rates,
    ensure_directory,
    ffprobe_duration,
    get_torch_peak_reserved_mb,
    normalize_audio,
    now_stamp,
    parse_cuda_device_index,
    query_gpu_memory_used_mb,
    reset_torch_peak_memory,
    resolve_device,
    resolve_models,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="擬似ストリーミング ASR 評価")
    parser.add_argument("--manifest", type=Path, required=True, help="manifest.jsonl")
    parser.add_argument("--dataset-name", required=True, help="結果表示用データセット名")
    parser.add_argument("--models", nargs="+", required=True, help="モデル alias")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--limit", type=int, default=None, help="先頭 N 件のみ評価")
    parser.add_argument("--log-every", type=int, default=20, help="進捗ログ間隔")
    parser.add_argument(
        "--stream-chunk-seconds",
        type=float,
        default=2.0,
        help="擬似ストリーミングで送る 1 chunk の秒数",
    )
    parser.add_argument(
        "--min-chunk-audio-seconds",
        type=float,
        default=1.0,
        help="短すぎる tail chunk を無音パディングする最小秒数",
    )
    parser.add_argument(
        "--faster-whisper-size",
        default="medium",
        help="faster_whisper alias 用モデルサイズ",
    )
    parser.add_argument(
        "--qwen-max-new-tokens",
        type=int,
        default=2048,
        help="Qwen3-ASR 用 max_new_tokens",
    )
    parser.add_argument(
        "--qwen-max-inference-batch-size",
        type=int,
        default=8,
        help="Qwen3-ASR 用 max_inference_batch_size",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="結果保存先。未指定時は benchmarks/<timestamp>/<dataset_name>_streaming",
    )
    return parser.parse_args()


def load_manifest(path: Path, limit: int | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    if not rows:
        raise SystemExit(f"manifest が空です: {path}")
    return rows


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def concat_text(chunks: list[str], language: str | None) -> str:
    parts = [chunk.strip() for chunk in chunks if chunk.strip()]
    if not parts:
        return ""
    if (language or "").startswith("ja"):
        return "".join(parts)
    return " ".join(parts)


def maybe_clear_torch_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        return


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=True)


def split_stream_audio(source: Path, output_dir: Path, chunk_seconds: float) -> list[Path]:
    pattern = output_dir / "chunk_%04d.wav"
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-f",
            "segment",
            "-segment_time",
            str(chunk_seconds),
            "-c",
            "copy",
            "-reset_timestamps",
            "1",
            str(pattern),
        ]
    )
    chunks = sorted(output_dir.glob("chunk_*.wav"))
    if not chunks:
        raise RuntimeError("音声分割に失敗しました。ffmpeg の出力を確認してください。")
    return chunks


def ensure_min_chunk_duration(chunk_path: Path, original_duration_s: float, min_duration_s: float) -> Path:
    if original_duration_s >= min_duration_s:
        return chunk_path

    padded_path = chunk_path.with_name(f"{chunk_path.stem}_padded.wav")
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(chunk_path),
            "-af",
            f"apad=pad_dur={max(0.0, min_duration_s - original_duration_s):.3f}",
            "-t",
            f"{min_duration_s:.3f}",
            str(padded_path),
        ]
    )
    return padded_path


def stream_one_item(
    adapter: Any,
    item: dict[str, Any],
    language: str | None,
    stream_chunk_seconds: float,
    min_chunk_audio_seconds: float,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="streaming-item-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        source_audio = Path(item["audio_path"])
        normalized_path = temp_dir / "normalized.wav"
        normalize_audio(source_audio, normalized_path, DEFAULT_SAMPLE_RATE)

        chunks_dir = temp_dir / "chunks"
        ensure_directory(chunks_dir)
        chunks = split_stream_audio(normalized_path, chunks_dir, max(0.1, stream_chunk_seconds))

        chunk_results: list[dict[str, Any]] = []
        chunk_texts: list[str] = []
        cumulative_audio_s = 0.0
        first_partial_latency_s: float | None = None
        started_all = time.perf_counter()

        for chunk_index, chunk_path in enumerate(chunks):
            chunk_audio_s = ffprobe_duration(chunk_path)
            model_input_path = ensure_min_chunk_duration(
                chunk_path=chunk_path,
                original_duration_s=chunk_audio_s,
                min_duration_s=min_chunk_audio_seconds,
            )
            started = time.perf_counter()
            text = adapter.transcribe(model_input_path, language).strip()
            wall_time_s = time.perf_counter() - started
            cumulative_audio_s += chunk_audio_s

            if text and first_partial_latency_s is None:
                first_partial_latency_s = cumulative_audio_s + wall_time_s

            chunk_texts.append(text)
            chunk_results.append(
                {
                    "chunk_index": chunk_index,
                    "chunk_path": str(chunk_path),
                    "model_input_path": str(model_input_path),
                    "audio_duration_s": chunk_audio_s,
                    "model_input_duration_s": ffprobe_duration(model_input_path),
                    "wall_time_s": wall_time_s,
                    "text": text,
                    "e2e_latency_s": cumulative_audio_s + wall_time_s,
                }
            )

        total_wall_s = time.perf_counter() - started_all
        final_text = concat_text(chunk_texts, language)
        final_latency_s = chunk_results[-1]["wall_time_s"] if chunk_results else None
        return {
            "id": item["id"],
            "audio_path": item["audio_path"],
            "reference_text": item["reference_text"],
            "hypothesis_text": final_text,
            "duration_s": float(item.get("duration_s", cumulative_audio_s)),
            "num_stream_chunks": len(chunk_results),
            "first_partial_latency_s": first_partial_latency_s,
            "final_latency_s": final_latency_s,
            "total_wall_s": total_wall_s,
            "chunks": chunk_results,
        }


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
    first_partial_latencies: list[float] = []
    final_latencies: list[float] = []
    chunk_wall_times: list[float] = []
    total_audio_s = 0.0
    started_all = time.perf_counter()

    for index, item in enumerate(items, start=1):
        prediction = stream_one_item(
            adapter=adapter,
            item=item,
            language=args.language or None,
            stream_chunk_seconds=args.stream_chunk_seconds,
            min_chunk_audio_seconds=args.min_chunk_audio_seconds,
        )
        predictions.append(prediction)
        reference_parts.append(item["reference_text"].strip())
        hypothesis_parts.append(prediction["hypothesis_text"].strip())
        total_audio_s += float(item.get("duration_s", prediction["duration_s"]))

        if prediction["first_partial_latency_s"] is not None:
            first_partial_latencies.append(prediction["first_partial_latency_s"])
        if prediction["final_latency_s"] is not None:
            final_latencies.append(prediction["final_latency_s"])
        chunk_wall_times.extend(chunk["wall_time_s"] for chunk in prediction["chunks"])

        if index == 1 or index % max(1, args.log_every) == 0 or index == len(items):
            first_partial = prediction["first_partial_latency_s"]
            first_partial_str = f"{first_partial:.2f}s" if first_partial is not None else "n/a"
            print(
                f"[{args.dataset_name}:{model['alias']}] "
                f"item={index}/{len(items)} "
                f"stream_chunks={prediction['num_stream_chunks']} "
                f"audio={prediction['duration_s']:.1f}s "
                f"first_partial={first_partial_str}"
            )

    total_wall_s = time.perf_counter() - started_all
    combined_reference = "\n".join(reference_parts)
    combined_hypothesis = "\n".join(hypothesis_parts)
    metrics = compute_error_rates(combined_reference, combined_hypothesis)

    report = {
        "dataset_name": args.dataset_name,
        "model_alias": model["alias"],
        "repo_id": model["repo_id"],
        "stream_mode": "chunk_append",
        "stream_chunk_seconds": args.stream_chunk_seconds,
        "num_items": len(items),
        "total_audio_s": total_audio_s,
        "total_wall_s": total_wall_s,
        "real_time_factor": total_wall_s / total_audio_s if total_audio_s > 0 else None,
        "x_realtime": total_audio_s / total_wall_s if total_wall_s > 0 else None,
        "reference_metrics": metrics,
        "first_partial_latency_mean_s": statistics.mean(first_partial_latencies) if first_partial_latencies else None,
        "first_partial_latency_p95_s": percentile(first_partial_latencies, 0.95),
        "final_latency_mean_s": statistics.mean(final_latencies) if final_latencies else None,
        "final_latency_p95_s": percentile(final_latencies, 0.95),
        "chunk_wall_time_mean_s": statistics.mean(chunk_wall_times) if chunk_wall_times else None,
        "chunk_wall_time_p95_s": percentile(chunk_wall_times, 0.95),
        "avg_stream_chunks_per_item": (
            statistics.mean(prediction["num_stream_chunks"] for prediction in predictions)
            if predictions else None
        ),
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
    output_root = args.output_dir or (DEFAULT_OUTPUT_ROOT / now_stamp() / f"{args.dataset_name}_streaming")
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
            f"- {report['model_alias']}: "
            f"xRealtime={report['x_realtime']:.2f} "
            f"CER={cer_str} "
            f"first_partial_mean={report['first_partial_latency_mean_s']:.2f}s "
            f"final_mean={report['final_latency_mean_s']:.2f}s"
        )


if __name__ == "__main__":
    main()
