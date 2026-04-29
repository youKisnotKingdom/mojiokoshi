#!/usr/bin/env python3
"""
Build a longer ASR evaluation set by concatenating paired audio/reference files.

This is intended for short-utterance datasets where per-file ASR evaluation may
underestimate performance because each item has too little context.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from benchmark_asr import ffprobe_duration


AUDIO_EXTENSIONS = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac")
REFERENCE_EXTENSIONS = (".txt", ".text", ".md", ".markdown")


@dataclass(frozen=True)
class Pair:
    audio_path: Path
    reference_text: str
    duration_s: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="短い音声/正解ペアを連結して manifest を作成")
    parser.add_argument("--audio-dir", type=Path, required=True)
    parser.add_argument("--reference-dir", "--drafts-dir", type=Path, default=None)
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=None,
        help="既存 manifest.jsonl を使う。duration/reference_text を再利用するため高速。",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dataset-name", default="concatenated_dataset")
    parser.add_argument("--target-seconds", type=float, default=300.0, help="1連結ファイルの目標秒数")
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--skip-missing", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def find_reference(reference_dir: Path, stem: str) -> Path | None:
    for extension in REFERENCE_EXTENSIONS:
        candidate = reference_dir / f"{stem}{extension}"
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def collect_pairs(audio_dir: Path, reference_dir: Path, skip_missing: bool, limit: int | None) -> list[Pair]:
    pairs: list[Pair] = []
    audio_paths = [
        path
        for path in sorted(audio_dir.iterdir(), key=lambda p: p.name)
        if path.is_file() and path.suffix.casefold() in AUDIO_EXTENSIONS
    ]
    for audio_path in audio_paths:
        reference_path = find_reference(reference_dir, audio_path.stem)
        if reference_path is None:
            if skip_missing:
                continue
            raise SystemExit(f"reference not found for audio stem: {audio_path.stem}")
        pairs.append(
            Pair(
                audio_path=audio_path.resolve(),
                reference_text=reference_path.read_text(encoding="utf-8").strip(),
                duration_s=ffprobe_duration(audio_path),
            )
        )
        if limit is not None and len(pairs) >= limit:
            break
    if not pairs:
        raise SystemExit("No audio/reference pairs found.")
    return pairs


def collect_pairs_from_manifest(path: Path, limit: int | None) -> list[Pair]:
    pairs: list[Pair] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            pairs.append(
                Pair(
                    audio_path=Path(item["audio_path"]).expanduser().resolve(),
                    reference_text=str(item.get("reference_text") or "").strip(),
                    duration_s=float(item.get("duration_s") or 0.0),
                )
            )
            if limit is not None and len(pairs) >= limit:
                break
    if not pairs:
        raise SystemExit(f"manifest is empty: {path}")
    missing = [str(pair.audio_path) for pair in pairs if not pair.audio_path.exists()]
    if missing:
        raise SystemExit(f"audio referenced by manifest is missing: {missing[0]}")
    return pairs


def group_pairs(pairs: Iterable[Pair], target_seconds: float) -> list[list[Pair]]:
    groups: list[list[Pair]] = []
    current: list[Pair] = []
    current_duration = 0.0
    for pair in pairs:
        if current and current_duration + pair.duration_s > target_seconds:
            groups.append(current)
            current = []
            current_duration = 0.0
        current.append(pair)
        current_duration += pair.duration_s
    if current:
        groups.append(current)
    return groups


def escape_ffmpeg_concat_path(path: Path) -> str:
    return str(path).replace("'", "'\\''")


def run_ffmpeg_concat(group: list[Pair], output_path: Path) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".concat.txt", delete=False) as handle:
        list_path = Path(handle.name)
        for pair in group:
            handle.write(f"file '{escape_ffmpeg_concat_path(pair.audio_path)}'\n")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ],
            check=True,
        )
    finally:
        list_path.unlink(missing_ok=True)


def write_jsonl(path: Path, items: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def portable_path(path: Path) -> str:
    resolved = path.resolve()
    cwd = Path.cwd().resolve()
    try:
        return resolved.relative_to(cwd).as_posix()
    except ValueError:
        return str(resolved)


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    audio_output_dir = output_dir / "audio"
    reference_output_dir = output_dir / "reference"
    audio_output_dir.mkdir(parents=True, exist_ok=True)
    reference_output_dir.mkdir(parents=True, exist_ok=True)

    if args.source_manifest:
        pairs = collect_pairs_from_manifest(args.source_manifest, args.limit)
    else:
        if args.reference_dir is None:
            raise SystemExit("--source-manifest を使わない場合は --reference-dir または --drafts-dir が必要です。")
        pairs = collect_pairs(
            audio_dir=args.audio_dir,
            reference_dir=args.reference_dir,
            skip_missing=args.skip_missing,
            limit=args.limit,
        )
    groups = group_pairs(pairs, args.target_seconds)

    manifest_items: list[dict] = []
    total_source_duration = 0.0
    for index, group in enumerate(groups, start=1):
        group_id = f"{args.dataset_name}_{index:04d}"
        audio_output_path = audio_output_dir / f"{group_id}.wav"
        reference_output_path = reference_output_dir / f"{group_id}.txt"

        run_ffmpeg_concat(group, audio_output_path)
        reference_text = "\n".join(pair.reference_text for pair in group).strip()
        reference_output_path.write_text(f"{reference_text}\n", encoding="utf-8")

        source_duration = sum(pair.duration_s for pair in group)
        output_duration = ffprobe_duration(audio_output_path)
        total_source_duration += source_duration
        manifest_items.append(
            {
                "id": group_id,
                "audio_path": portable_path(audio_output_path),
                "reference_text": reference_text,
                "duration_s": output_duration,
                "source_count": len(group),
                "source_duration_s": source_duration,
                "reference_path": portable_path(reference_output_path),
            }
        )
        print(
            f"[{group_id}] files={len(group)} "
            f"source_audio={source_duration:.1f}s output_audio={output_duration:.1f}s",
            flush=True,
        )

    manifest_path = output_dir / "manifest.jsonl"
    write_jsonl(manifest_path, manifest_items)
    metadata = {
        "dataset_name": args.dataset_name,
        "source_audio_dir": str(args.audio_dir.resolve()),
        "source_reference_dir": str(args.reference_dir.resolve()) if args.reference_dir else None,
        "source_manifest": str(args.source_manifest.resolve()) if args.source_manifest else None,
        "target_seconds": args.target_seconds,
        "source_items": len(pairs),
        "concatenated_items": len(manifest_items),
        "total_source_audio_s": total_source_duration,
        "total_output_audio_s": sum(float(item["duration_s"]) for item in manifest_items),
        "manifest_path": str(manifest_path),
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"manifest: {manifest_path}")
    print(
        f"items: {len(pairs)} -> {len(manifest_items)} "
        f"audio={metadata['total_output_audio_s']:.1f}s"
    )


if __name__ == "__main__":
    main()
