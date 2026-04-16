#!/usr/bin/env python3
"""
report.json を横断して主要指標を一覧表示する。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ASR ベンチマーク report の簡易集計")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("benchmarks"),
        help="探索ルート",
    )
    parser.add_argument(
        "--pattern",
        default="**/report.json",
        help="glob pattern",
    )
    return parser.parse_args()


def load_rows(root: Path, pattern: str) -> list[dict]:
    rows: list[dict] = []
    for report_path in sorted(root.glob(pattern)):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        metrics = report.get("reference_metrics") or {}
        cer = metrics.get("cer")
        wer = metrics.get("wer")
        rows.append(
            {
                "path": str(report_path),
                "model": report.get("model_alias"),
                "dataset": report.get("dataset_name"),
                "num_chunks": report.get("num_chunks"),
                "num_items": report.get("num_items"),
                "audio_s": report.get("total_audio_s"),
                "wall_s": report.get("total_wall_s"),
                "x_realtime": report.get("x_realtime"),
                "cer_pct": cer * 100 if isinstance(cer, (int, float)) else None,
                "wer_pct": wer * 100 if isinstance(wer, (int, float)) else None,
                "gpu_load_mb": report.get("gpu_memory_after_load_mb"),
                "gpu_run_mb": report.get("gpu_memory_after_run_mb"),
                "torch_peak_mb": report.get("torch_peak_reserved_mb"),
            }
        )
    return rows


def format_value(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def main() -> None:
    args = parse_args()
    rows = load_rows(args.root, args.pattern)
    if not rows:
        raise SystemExit("report.json が見つかりませんでした。")

    rows.sort(key=lambda row: (row["dataset"] or "", row["model"] or "", row["path"]))
    header = [
        "dataset",
        "model",
        "chunks",
        "items",
        "audio_s",
        "wall_s",
        "x_rt",
        "cer%",
        "wer%",
        "gpu_load",
        "gpu_run",
        "torch_peak",
        "path",
    ]
    print("\t".join(header))
    for row in rows:
        print(
            "\t".join(
                [
                    format_value(row["dataset"]),
                    format_value(row["model"]),
                    format_value(row["num_chunks"]),
                    format_value(row["num_items"]),
                    format_value(row["audio_s"]),
                    format_value(row["wall_s"]),
                    format_value(row["x_realtime"]),
                    format_value(row["cer_pct"]),
                    format_value(row["wer_pct"]),
                    format_value(row["gpu_load_mb"]),
                    format_value(row["gpu_run_mb"]),
                    format_value(row["torch_peak_mb"]),
                    row["path"],
                ]
            )
        )


if __name__ == "__main__":
    main()
