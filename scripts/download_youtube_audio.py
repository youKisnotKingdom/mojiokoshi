#!/usr/bin/env python3
"""
YouTube から長尺音声評価用データを取得するスクリプト

出力:
  benchmark_data/audio/<video_id>.mp3
  benchmark_data/subtitles/<video_id>.<lang>.srt
  benchmark_data/reference/<video_id>.txt
  benchmark_data/metadata/<video_id>.json

例:
  # 1本だけ取得
  python scripts/download_youtube_audio.py BmtnWaUvX_0

  # manifest 全件取得
  python scripts/download_youtube_audio.py --all
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "config" / "japanese_longform_youtube_videos.json"
DATA_ROOT = Path(__file__).resolve().parent.parent / "benchmark_data"
DEFAULT_SUB_LANGS = "ja-orig,ja"


def resolve_ytdlp_command() -> list[str]:
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    if shutil.which("uvx"):
        return ["uvx", "yt-dlp"]
    raise SystemExit("`yt-dlp` も `uvx yt-dlp` も見つかりません。")


def load_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def url_for(video_id_or_url: str) -> str:
    if video_id_or_url.startswith("http://") or video_id_or_url.startswith("https://"):
        return video_id_or_url
    return f"https://www.youtube.com/watch?v={video_id_or_url}"


def run_command(command: list[str]) -> None:
    subprocess.run(command, check=True)


def download_audio(video: str, audio_dir: Path) -> None:
    output_template = str(audio_dir / "%(id)s.%(ext)s")
    command = resolve_ytdlp_command() + [
        "-x",
        "--audio-format",
        "mp3",
        "--output",
        output_template,
        url_for(video),
    ]
    run_command(command)


def download_subtitles(video: str, subtitle_dir: Path, sub_langs: str) -> None:
    output_template = str(subtitle_dir / "%(id)s.%(ext)s")
    command = resolve_ytdlp_command() + [
        "--skip-download",
        "--write-auto-subs",
        "--sub-langs",
        sub_langs,
        "--sub-format",
        "srt",
        "--convert-subs",
        "srt",
        "--output",
        output_template,
        url_for(video),
    ]
    run_command(command)


def pick_subtitle_file(video_id: str, subtitle_dir: Path) -> Path | None:
    candidates = [
        subtitle_dir / f"{video_id}.ja-orig.srt",
        subtitle_dir / f"{video_id}.ja.srt",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    matches = sorted(subtitle_dir.glob(f"{video_id}.*.srt"))
    return matches[0] if matches else None


def clean_subtitle_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def subtitle_to_reference(subtitle_path: Path, reference_path: Path) -> None:
    lines = subtitle_path.read_text(encoding="utf-8").splitlines()
    collected: list[str] = []
    previous = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.isdigit():
            continue
        if "-->" in stripped:
            continue
        cleaned = clean_subtitle_text(stripped)
        if not cleaned:
            continue
        if cleaned == previous:
            continue
        collected.append(cleaned)
        previous = cleaned
    reference_path.write_text("\n".join(collected) + "\n", encoding="utf-8")


def write_metadata(video_id: str, audio_dir: Path, subtitle_path: Path | None, metadata_dir: Path, manifest_entry: dict[str, Any] | None) -> None:
    audio_candidates = sorted(audio_dir.glob(f"{video_id}.*"))
    payload = {
        "video_id": video_id,
        "audio_path": str(audio_candidates[0]) if audio_candidates else None,
        "subtitle_path": str(subtitle_path) if subtitle_path else None,
    }
    if manifest_entry:
        payload.update(manifest_entry)
    (metadata_dir / f"{video_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YouTube の長尺日本語音声データを取得")
    parser.add_argument("videos", nargs="*", help="動画 ID または URL")
    parser.add_argument("--all", action="store_true", help="manifest にある全件を取得")
    parser.add_argument("--sub-langs", default=DEFAULT_SUB_LANGS, help="字幕言語。既定: ja-orig,ja")
    parser.add_argument("--audio-dir", type=Path, default=DATA_ROOT / "audio")
    parser.add_argument("--subtitle-dir", type=Path, default=DATA_ROOT / "subtitles")
    parser.add_argument("--reference-dir", type=Path, default=DATA_ROOT / "reference")
    parser.add_argument("--metadata-dir", type=Path, default=DATA_ROOT / "metadata")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = load_manifest()
    manifest_map = {item["id"]: item for item in manifest["videos"]}

    videos = list(args.videos)
    if args.all:
        videos = [item["id"] for item in manifest["videos"]]
    if not videos:
        raise SystemExit("動画 ID を指定するか、`--all` を指定してください。")

    ensure_dir(args.audio_dir)
    ensure_dir(args.subtitle_dir)
    ensure_dir(args.reference_dir)
    ensure_dir(args.metadata_dir)

    for video in videos:
        video_id = video.split("v=")[-1] if "youtube.com" in video else video
        print(f"Downloading audio: {video}")
        download_audio(video, args.audio_dir)

        print(f"Downloading subtitles: {video}")
        download_subtitles(video, args.subtitle_dir, args.sub_langs)

        subtitle_path = pick_subtitle_file(video_id, args.subtitle_dir)
        if subtitle_path:
            reference_path = args.reference_dir / f"{video_id}.txt"
            subtitle_to_reference(subtitle_path, reference_path)
            print(f"Reference text created: {reference_path}")
        else:
            print(f"Warning: subtitle not found for {video_id}", file=sys.stderr)

        write_metadata(
            video_id=video_id,
            audio_dir=args.audio_dir,
            subtitle_path=subtitle_path,
            metadata_dir=args.metadata_dir,
            manifest_entry=manifest_map.get(video_id),
        )


if __name__ == "__main__":
    main()
