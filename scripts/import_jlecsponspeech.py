#!/usr/bin/env python3
"""
JLecSponSpeech の ZIP から gold reference を生成するスクリプト

想定入力:
  benchmark_data/matsunaga22_filler_20230526.zip
  benchmark_data/matsunaga22_filler_20230526 (2).zip

出力:
  benchmark_data/reference_gold/<video_id>.txt
  benchmark_data/reference_gold_tagged/<video_id>.txt
  benchmark_data/metadata/<video_id>.json に gold 参照を追記
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "config" / "japanese_longform_youtube_videos.json"
DEFAULT_ZIP_CANDIDATES = [
    ROOT / "benchmark_data" / "matsunaga22_filler_20230526.zip",
    ROOT / "benchmark_data" / "matsunaga22_filler_20230526 (2).zip",
]
DEFAULT_REFERENCE_DIR = ROOT / "benchmark_data" / "reference_gold"
DEFAULT_TAGGED_DIR = ROOT / "benchmark_data" / "reference_gold_tagged"
DEFAULT_METADATA_DIR = ROOT / "benchmark_data" / "metadata"

NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
TAG_PATTERN = re.compile(r"<[^>]+>")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JLecSponSpeech から gold reference を生成")
    parser.add_argument("--zip", dest="zip_path", type=Path, default=None)
    parser.add_argument("--reference-dir", type=Path, default=DEFAULT_REFERENCE_DIR)
    parser.add_argument("--tagged-dir", type=Path, default=DEFAULT_TAGGED_DIR)
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    return parser.parse_args()


def resolve_zip_path(path: Path | None) -> Path:
    if path and path.exists():
        return path
    for candidate in DEFAULT_ZIP_CANDIDATES:
        if candidate.exists():
            return candidate
    raise SystemExit("JLecSponSpeech の ZIP が見つかりません。benchmark_data/ に配置してください。")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_manifest() -> list[dict]:
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data["videos"]


def load_shared_strings(zip_file: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []

    root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    shared: list[str] = []
    for si in root.findall("a:si", NS):
        texts = []
        for t in si.iterfind(".//a:t", NS):
            texts.append(t.text or "")
        shared.append("".join(texts))
    return shared


def read_sheet_rows(zip_file: ZipFile) -> list[dict[str, str]]:
    shared = load_shared_strings(zip_file)
    sheet = ET.fromstring(zip_file.read("xl/worksheets/sheet1.xml"))
    rows: list[dict[str, str]] = []
    for row in sheet.findall(".//a:sheetData/a:row", NS):
        values: dict[str, str] = {}
        for cell in row.findall("a:c", NS):
            ref = cell.attrib.get("r", "")
            col = "".join(ch for ch in ref if ch.isalpha())
            cell_type = cell.attrib.get("t")
            raw = ""
            value_node = cell.find("a:v", NS)
            if value_node is not None:
                raw = value_node.text or ""
            if cell_type == "s" and raw:
                values[col] = shared[int(raw)]
            else:
                values[col] = raw
        rows.append(values)
    return rows


def extract_transcripts(zip_path: Path) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    with ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if not name.endswith(".xlsx") or "utokyo_lecture_" not in name:
                continue
            with archive.open(name) as fh:
                workbook_bytes = fh.read()
            workbook_path = Path(name).name
            # xlsx is also a zip archive
            from io import BytesIO

            with ZipFile(BytesIO(workbook_bytes)) as workbook_zip:
                rows = read_sheet_rows(workbook_zip)
            result[workbook_path] = rows[1:]
    return result


def strip_tags(text: str) -> str:
    no_tags = TAG_PATTERN.sub("", text)
    return re.sub(r"\s+", " ", no_tags).strip()


def build_reference(rows: list[dict[str, str]]) -> tuple[str, str]:
    plain_lines: list[str] = []
    tagged_lines: list[str] = []
    for row in rows:
        text = (row.get("D") or "").strip()
        if not text:
            continue
        tagged_lines.append(text)
        plain = strip_tags(text)
        if plain:
            plain_lines.append(plain)
    return "\n".join(plain_lines) + "\n", "\n".join(tagged_lines) + "\n"


def update_metadata(metadata_path: Path, gold_path: Path, tagged_path: Path) -> None:
    if metadata_path.exists():
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    else:
        payload = {}
    payload["gold_reference_path"] = str(gold_path)
    payload["gold_reference_tagged_path"] = str(tagged_path)
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    zip_path = resolve_zip_path(args.zip_path)
    ensure_dir(args.reference_dir)
    ensure_dir(args.tagged_dir)
    ensure_dir(args.metadata_dir)

    videos = load_manifest()
    transcripts = extract_transcripts(zip_path)

    for video in videos:
        workbook_name = video.get("jlecsponspeech_file")
        if not workbook_name:
            continue
        rows = transcripts.get(workbook_name)
        if rows is None:
            print(f"skip: {video['id']} -> {workbook_name} not found")
            continue

        plain_text, tagged_text = build_reference(rows)
        gold_path = args.reference_dir / f"{video['id']}.txt"
        tagged_path = args.tagged_dir / f"{video['id']}.txt"
        gold_path.write_text(plain_text, encoding="utf-8")
        tagged_path.write_text(tagged_text, encoding="utf-8")
        update_metadata(args.metadata_dir / f"{video['id']}.json", gold_path, tagged_path)
        print(f"created: {video['id']} <- {workbook_name}")


if __name__ == "__main__":
    main()
