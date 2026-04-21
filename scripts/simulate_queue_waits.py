#!/usr/bin/env python3
"""Benchmark-derived queue wait simulation for transcription operations."""

from __future__ import annotations

import argparse
import heapq
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelProfile:
    alias: str
    display_name: str
    x_realtime: float
    recommended_parallel_workers: int
    note: str


MODEL_PROFILES: dict[str, ModelProfile] = {
    "parakeet_ja": ModelProfile("parakeet_ja", "Parakeet", 144.16, 1, "精度優先。16GB GPU では 1 worker 想定。"),
    "cohere_transcribe": ModelProfile("cohere_transcribe", "Cohere", 169.80, 1, "速いが現状は 1 worker 想定。"),
    "reazon_zipformer": ModelProfile("reazon_zipformer", "Reazon Zipformer", 286.13, 2, "低VRAM。SKIP LOCKED 導入後なら 2 worker 候補。"),
    "reazon_nemo_v2": ModelProfile("reazon_nemo_v2", "Reazon NeMo v2", 40.62, 1, "長尺候補だが VRAM と速度の両面から 1 worker 想定。"),
    "faster_whisper": ModelProfile("faster_whisper", "faster-whisper", 19.43, 2, "保守的な代替。専用 GPU 前提で 2 worker 候補。"),
}

SCENARIOS: dict[str, list[int]] = {
    "3_users_1h_each": [3600, 3600, 3600],
    "5_users_1h_each": [3600, 3600, 3600, 3600, 3600],
    "10_users_1h_each": [3600] * 10,
    "mixed_5_users": [1800, 3600, 7200, 1800, 3600],
}


def format_seconds(seconds: float) -> str:
    seconds = round(seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{sec:02d}s"
    if minutes:
        return f"{minutes}m{sec:02d}s"
    return f"{sec}s"


def simulate_queue(durations_s: list[int], x_realtime: float, workers: int) -> dict[str, float | list[float]]:
    worker_heap = [0.0] * workers
    waits: list[float] = []
    finishes: list[float] = []

    for audio_s in durations_s:
        service_s = audio_s / x_realtime
        start_s = heapq.heappop(worker_heap)
        finish_s = start_s + service_s
        waits.append(start_s)
        finishes.append(finish_s)
        heapq.heappush(worker_heap, finish_s)

    sorted_waits = sorted(waits)
    p95_index = max(0, int(0.95 * (len(sorted_waits) - 1)))
    return {
        "workers": workers,
        "waits_s": waits,
        "finishes_s": finishes,
        "avg_wait_s": sum(waits) / len(waits),
        "p95_wait_s": sorted_waits[p95_index],
        "makespan_s": max(finishes),
    }


def build_report(model_aliases: list[str]) -> dict:
    report = {"models": []}
    for alias in model_aliases:
        profile = MODEL_PROFILES[alias]
        entry = {
            "alias": profile.alias,
            "display_name": profile.display_name,
            "x_realtime": profile.x_realtime,
            "note": profile.note,
            "scenarios": {},
        }
        for name, durations in SCENARIOS.items():
            entry["scenarios"][name] = {
                "current_single_worker": simulate_queue(durations, profile.x_realtime, 1),
                "recommended_parallel": simulate_queue(durations, profile.x_realtime, profile.recommended_parallel_workers),
            }
        report["models"].append(entry)
    return report


def to_markdown(report: dict) -> str:
    lines = [
        "# ASR Operations Concurrency Report",
        "",
        "更新日: 2026-04-21",
        "",
        "このレポートは、ベンチマーク実測の `xRealtime` を使って、同時アクセス時の待ち時間を概算したものです。",
        "現在の実装は worker 1 本前提なので、`current_single_worker` が現実の挙動に近いです。",
        "`recommended_parallel` は `SKIP LOCKED` 導入後の仮説値です。",
        "",
        "## 実装の前提",
        "",
        "- 現在の本番文字起こし経路は `app/services/transcription.py` の `faster-whisper` 実装のみです。",
        "- `job.engine` は保存されますが、worker 実行時に Qwen や vLLM へ分岐していません。",
        "- `vLLM` はベンチ用 `qwen-asr[vllm]` スクリプトでのみ使っていて、アプリ本体の並列推論には入っていません。",
        "- そのため、現状のアプリには vLLM の request batching / continuous batching はありません。",
        "",
    ]

    scenario_labels = {
        "3_users_1h_each": "3人が同時に1時間音声を投げる",
        "5_users_1h_each": "5人が同時に1時間音声を投げる",
        "10_users_1h_each": "10人が同時に1時間音声を投げる",
        "mixed_5_users": "5人が 30分 / 60分 / 120分 / 30分 / 60分 を同時投入",
    }

    for model in report["models"]:
        lines.extend([
            f"## {model['display_name']}",
            "",
            f"- xRealtime: `{model['x_realtime']:.2f}x`",
            f"- 補足: {model['note']}",
            "",
        ])
        lines.append("| シナリオ | 現行: 平均待ち時間 | 現行: 全件完了 | 仮説: worker数 | 仮説: 平均待ち時間 | 仮説: 全件完了 |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for key, label in scenario_labels.items():
            cur = model["scenarios"][key]["current_single_worker"]
            par = model["scenarios"][key]["recommended_parallel"]
            lines.append(
                f"| {label} | {format_seconds(cur['avg_wait_s'])} | {format_seconds(cur['makespan_s'])} | {par['workers']} | {format_seconds(par['avg_wait_s'])} | {format_seconds(par['makespan_s'])} |"
            )
        lines.append("")

    lines.extend([
        "## 運用判断",
        "",
        "- 現状のままなら、ジョブは複数積めても実行は 1 本ずつです。",
        "- `reazon_zipformer` は 1 本あたりの処理時間が短いので、直列でも待ち時間が読みやすいです。",
        "- `parakeet_ja` は精度優先としては十分速いですが、同時実行を前提にする設計ではありません。",
        "- `reazon_nemo_v2` は品質は良いですが、同時アクセス時の待ち時間は伸びやすいです。",
        "- 複数 worker を真面目にやるなら、先に `FOR UPDATE SKIP LOCKED` 相当の排他制御が必要です。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate queue wait times from benchmark-derived throughput")
    parser.add_argument("--models", nargs="+", default=list(MODEL_PROFILES.keys()), choices=list(MODEL_PROFILES.keys()))
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args()

    report = build_report(args.models)
    if args.output_json:
        args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.output_md:
        args.output_md.write_text(to_markdown(report), encoding="utf-8")
    if not args.output_json and not args.output_md:
        print(to_markdown(report))


if __name__ == "__main__":
    main()
