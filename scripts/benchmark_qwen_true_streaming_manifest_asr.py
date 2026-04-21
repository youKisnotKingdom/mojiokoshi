#!/usr/bin/env python3
"""
Qwen3-ASR の true streaming(vLLM backend) を manifest ベースで評価する。
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from benchmark_asr import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SAMPLE_RATE,
    compute_error_rates,
    ensure_directory,
    get_torch_peak_reserved_mb,
    normalize_audio,
    now_stamp,
    parse_cuda_device_index,
    query_gpu_memory_used_mb,
    reset_torch_peak_memory,
    resolve_cached_model_source,
)

LANGUAGE_CODE_TO_NAME = {
    "ja": "Japanese",
    "en": "English",
    "zh": "Chinese",
    "ko": "Korean",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Qwen true streaming(vLLM) 評価")
    parser.add_argument("--manifest", type=Path, required=True, help="manifest.jsonl")
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--repo-id", default="Qwen/Qwen3-ASR-0.6B")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--feed-seconds", type=float, default=0.5, help="1回に流し込む秒数")
    parser.add_argument("--decode-chunk-seconds", type=float, default=0.5, help="Qwen 側の streaming chunk サイズ")
    parser.add_argument("--unfixed-chunk-num", type=int, default=2)
    parser.add_argument("--unfixed-token-num", type=int, default=5)
    parser.add_argument("--reset-seconds", type=float, default=0.0, help="この秒数ごとに streaming state を確定して張り替える")
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.7)
    parser.add_argument("--max-model-len", type=int, default=32768)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--max-inference-batch-size", type=int, default=1)
    parser.add_argument("--enforce-eager", action="store_true")
    parser.add_argument("--cpu-offload-gb", type=float, default=0.0)
    parser.add_argument("--swap-space", type=float, default=4.0)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--log-every", type=int, default=20)
    parser.add_argument("--output-dir", type=Path, default=None)
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


def load_pcm16k(audio_path: Path) -> np.ndarray:
    pcm, sr = sf.read(audio_path, dtype="float32", always_2d=False)
    if sr != DEFAULT_SAMPLE_RATE:
        raise RuntimeError(f"想定外のサンプリングレートです: {sr}")
    if pcm.ndim != 1:
        pcm = pcm.mean(axis=1)
    return pcm.astype(np.float32, copy=False)


def iter_pcm_chunks(pcm16k: np.ndarray, samples_per_chunk: int) -> list[np.ndarray]:
    chunks: list[np.ndarray] = []
    for start in range(0, len(pcm16k), samples_per_chunk):
        chunk = pcm16k[start : start + samples_per_chunk]
        if len(chunk) == 0:
            continue
        chunks.append(chunk)
    return chunks


def benchmark_dataset(args: argparse.Namespace, items: list[dict[str, Any]], output_root: Path) -> dict[str, Any]:
    from qwen_asr import Qwen3ASRModel

    repo_source = resolve_cached_model_source(args.repo_id)
    device_index = parse_cuda_device_index(args.device)
    gpu_before_load_mb = None
    gpu_after_load_mb = None
    gpu_after_run_mb = None

    gpu_before_load_mb = query_gpu_memory_used_mb(device_index)
    reset_torch_peak_memory(device_index)
    model = Qwen3ASRModel.LLM(
        model=repo_source,
        gpu_memory_utilization=args.gpu_memory_utilization,
        max_model_len=args.max_model_len,
        max_inference_batch_size=args.max_inference_batch_size,
        max_new_tokens=args.max_new_tokens,
        enforce_eager=args.enforce_eager,
        cpu_offload_gb=args.cpu_offload_gb,
        swap_space=args.swap_space,
    )
    gpu_after_load_mb = query_gpu_memory_used_mb(device_index)

    first_partial_latencies: list[float] = []
    final_latencies: list[float] = []
    chunk_wall_times: list[float] = []
    predictions: list[dict[str, Any]] = []
    total_audio_s = 0.0
    total_wall_s = 0.0

    samples_per_feed = max(1, int(round(args.feed_seconds * DEFAULT_SAMPLE_RATE)))
    language_name = LANGUAGE_CODE_TO_NAME.get(args.language, args.language)

    for index, item in enumerate(items, start=1):
        item_started = time.perf_counter()
        with Path("/tmp").joinpath(f"qwen-stream-{index:04d}.wav").open("wb"):
            pass
        # Normalize to a temp file per item to make input conditions explicit.
        normalized_path = Path(f"/tmp/qwen-stream-{index:04d}.wav")
        normalize_audio(Path(item["audio_path"]), normalized_path, DEFAULT_SAMPLE_RATE)
        pcm16k = load_pcm16k(normalized_path)
        chunks = iter_pcm_chunks(pcm16k, samples_per_feed)

        state = model.init_streaming_state(
            language=language_name,
            chunk_size_sec=args.decode_chunk_seconds,
            unfixed_chunk_num=args.unfixed_chunk_num,
            unfixed_token_num=args.unfixed_token_num,
        )

        cumulative_audio_s = 0.0
        segment_audio_s = 0.0
        segment_index = 0
        first_partial_latency_s: float | None = None
        per_chunk: list[dict[str, Any]] = []
        final_text_parts: list[str] = []

        for chunk_index, pcm_chunk in enumerate(chunks):
            started = time.perf_counter()
            state = model.streaming_transcribe(pcm_chunk, state)
            wall_time_s = time.perf_counter() - started
            chunk_audio_s = len(pcm_chunk) / DEFAULT_SAMPLE_RATE
            cumulative_audio_s += chunk_audio_s
            segment_audio_s += chunk_audio_s
            chunk_wall_times.append(wall_time_s)
            if state.text.strip() and first_partial_latency_s is None:
                first_partial_latency_s = cumulative_audio_s + wall_time_s
            per_chunk.append(
                {
                    "chunk_index": chunk_index,
                    "segment_index": segment_index,
                    "audio_duration_s": chunk_audio_s,
                    "wall_time_s": wall_time_s,
                    "text": state.text,
                    "e2e_latency_s": cumulative_audio_s + wall_time_s,
                }
            )
            is_last_chunk = chunk_index == len(chunks) - 1
            should_reset = (
                args.reset_seconds > 0
                and not is_last_chunk
                and segment_audio_s >= args.reset_seconds
            )
            if should_reset:
                state = model.finish_streaming_transcribe(state)
                if state.text.strip():
                    final_text_parts.append(state.text.strip())
                state = model.init_streaming_state(
                    language=language_name,
                    chunk_size_sec=args.decode_chunk_seconds,
                    unfixed_chunk_num=args.unfixed_chunk_num,
                    unfixed_token_num=args.unfixed_token_num,
                )
                segment_audio_s = 0.0
                segment_index += 1

        finish_started = time.perf_counter()
        state = model.finish_streaming_transcribe(state)
        final_latency_s = time.perf_counter() - finish_started
        if state.text.strip():
            final_text_parts.append(state.text.strip())
        final_text = "".join(final_text_parts).strip()
        item_wall_s = time.perf_counter() - item_started
        total_wall_s += item_wall_s
        total_audio_s += float(item.get("duration_s", len(pcm16k) / DEFAULT_SAMPLE_RATE))
        if first_partial_latency_s is not None:
            first_partial_latencies.append(first_partial_latency_s)
        final_latencies.append(final_latency_s)
        predictions.append(
            {
                "id": item["id"],
                "audio_path": item["audio_path"],
                "reference_text": item["reference_text"],
                "hypothesis_text": final_text,
                "duration_s": float(item.get("duration_s", len(pcm16k) / DEFAULT_SAMPLE_RATE)),
                "num_stream_chunks": len(per_chunk),
                "first_partial_latency_s": first_partial_latency_s,
                "final_latency_s": final_latency_s,
                "total_wall_s": item_wall_s,
                "chunks": per_chunk,
            }
        )
        if index == 1 or index % max(1, args.log_every) == 0 or index == len(items):
            fp = f"{first_partial_latency_s:.2f}s" if first_partial_latency_s is not None else "n/a"
            print(
                f"[{args.dataset_name}:qwen_true_streaming] item={index}/{len(items)} "
                f"stream_chunks={len(per_chunk)} audio={predictions[-1]['duration_s']:.1f}s first_partial={fp}"
            )

        try:
            normalized_path.unlink(missing_ok=True)
        except Exception:
            pass

    gpu_after_run_mb = query_gpu_memory_used_mb(device_index)
    torch_peak_reserved_mb = get_torch_peak_reserved_mb(device_index)

    reference_text = "\n".join(item["reference_text"] for item in predictions)
    hypothesis_text = "\n".join(item["hypothesis_text"] for item in predictions)
    reference_metrics = compute_error_rates(reference_text, hypothesis_text)
    real_time_factor = total_wall_s / total_audio_s if total_audio_s > 0 else None
    x_realtime = total_audio_s / total_wall_s if total_wall_s > 0 else None

    report = {
        "dataset_name": args.dataset_name,
        "model_alias": "qwen_true_streaming",
        "repo_id": args.repo_id,
        "stream_mode": "qwen_vllm_true_streaming",
        "feed_seconds": args.feed_seconds,
        "decode_chunk_seconds": args.decode_chunk_seconds,
        "reset_seconds": args.reset_seconds,
        "enforce_eager": args.enforce_eager,
        "cpu_offload_gb": args.cpu_offload_gb,
        "swap_space": args.swap_space,
        "num_items": len(items),
        "total_audio_s": total_audio_s,
        "total_wall_s": total_wall_s,
        "real_time_factor": real_time_factor,
        "x_realtime": x_realtime,
        "reference_metrics": reference_metrics,
        "first_partial_latency_mean_s": statistics.mean(first_partial_latencies) if first_partial_latencies else None,
        "first_partial_latency_p95_s": percentile(first_partial_latencies, 0.95),
        "final_latency_mean_s": statistics.mean(final_latencies) if final_latencies else None,
        "final_latency_p95_s": percentile(final_latencies, 0.95),
        "chunk_wall_time_mean_s": statistics.mean(chunk_wall_times) if chunk_wall_times else None,
        "chunk_wall_time_p95_s": percentile(chunk_wall_times, 0.95),
        "avg_stream_chunks_per_item": statistics.mean(item["num_stream_chunks"] for item in predictions) if predictions else 0,
        "gpu_memory_before_load_mb": gpu_before_load_mb,
        "gpu_memory_after_load_mb": gpu_after_load_mb,
        "gpu_memory_after_run_mb": gpu_after_run_mb,
        "torch_peak_reserved_mb": torch_peak_reserved_mb,
    }

    ensure_directory(output_root)
    (output_root / "predictions.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in predictions) + "\n",
        encoding="utf-8",
    )
    (output_root / "reference.txt").write_text(reference_text, encoding="utf-8")
    (output_root / "hypothesis.txt").write_text(hypothesis_text, encoding="utf-8")
    (output_root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_payload = {
        "dataset_name": args.dataset_name,
        "model_alias": "qwen_true_streaming",
        "repo_id": args.repo_id,
        "feed_seconds": args.feed_seconds,
        "decode_chunk_seconds": args.decode_chunk_seconds,
        "x_realtime": x_realtime,
    }
    if reference_metrics is not None:
        summary_payload["cer_percent"] = reference_metrics["cer"] * 100.0
        summary_payload["wer_percent"] = reference_metrics["wer"] * 100.0
    (output_root / "summary.json").write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> None:
    args = parse_args()
    items = load_manifest(args.manifest, args.limit)
    output_root = args.output_dir or (DEFAULT_OUTPUT_ROOT / f"{now_stamp()}_{args.dataset_name}_qwen_true_stream")
    report = benchmark_dataset(args=args, items=items, output_root=output_root)
    cer_summary = ""
    if report["reference_metrics"] is not None and report["reference_metrics"]["cer"] is not None:
        cer_summary = f" CER={report['reference_metrics']['cer'] * 100:.2f}%"
    print(
        f"完了: {output_root}\n"
        f"- qwen_true_streaming: xRealtime={report['x_realtime']:.2f}"
        f"{cer_summary} "
        f"first_partial_mean={report['first_partial_latency_mean_s']:.2f}s "
        f"final_mean={report['final_latency_mean_s']:.2f}s"
    )


if __name__ == "__main__":
    main()
