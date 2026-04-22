#!/usr/bin/env python3
"""Build sliding text windows from transcription segments for LLM post-correction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_segments(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("result_segments"), list):
        return data["result_segments"]
    raise ValueError(f"Unsupported segment format: {path}")


def normalize_text(text: str) -> str:
    return " ".join(text.split()).strip()


def build_windows(
    segments: list[dict[str, Any]],
    window_seconds: float,
    step_seconds: float,
) -> list[dict[str, Any]]:
    if not segments:
        return []

    max_end = max(float(seg.get("end", 0.0) or 0.0) for seg in segments)
    windows: list[dict[str, Any]] = []
    start = 0.0
    index = 0

    while start <= max_end:
        end = start + window_seconds
        bucket = []
        for seg in segments:
            seg_start = float(seg.get("start", 0.0) or 0.0)
            seg_end = float(seg.get("end", seg_start) or seg_start)
            if seg_end <= start:
                continue
            if seg_start >= end:
                continue
            text = normalize_text(str(seg.get("text", "")))
            if text:
                bucket.append(
                    {
                        "start": seg_start,
                        "end": seg_end,
                        "text": text,
                    }
                )

        if bucket:
            merged_text = " ".join(item["text"] for item in bucket)
            windows.append(
                {
                    "window_index": index,
                    "window_start": round(start, 3),
                    "window_end": round(end, 3),
                    "text": merged_text,
                    "segments": bucket,
                }
            )
            index += 1

        start += step_seconds

    return windows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments_json", type=Path, help="Path to result_segments JSON or wrapper JSON")
    parser.add_argument("--window-seconds", type=float, default=15.0)
    parser.add_argument("--step-seconds", type=float, default=10.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    segments = load_segments(args.segments_json)
    windows = build_windows(segments, args.window_seconds, args.step_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(windows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(windows)} windows to {args.output}")


if __name__ == "__main__":
    main()
