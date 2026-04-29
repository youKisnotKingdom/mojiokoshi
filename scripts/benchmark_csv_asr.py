#!/usr/bin/env python3
"""
Run ASR benchmarks from a CSV file and a matching audio directory, or from
paired audio/reference directories.

The CSV needs one column that identifies the audio file and one column that
contains the reference text. Common column names are detected automatically.

Directory mode pairs files by basename/stem, for example:

    audio/sample001.wav
    drafts/sample001.txt
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from benchmark_asr import (
    DEFAULT_OUTPUT_ROOT,
    ensure_directory,
    ffprobe_duration,
    now_stamp,
    resolve_device,
    resolve_models,
)
from benchmark_manifest_asr import benchmark_dataset


AUDIO_COLUMN_CANDIDATES = (
    "audio_path",
    "audio_filepath",
    "path",
    "filepath",
    "file",
    "filename",
    "audio",
    "wav",
    "音声",
    "音声ファイル",
    "ファイル名",
)
REFERENCE_COLUMN_CANDIDATES = (
    "reference_text",
    "reference",
    "text",
    "transcript",
    "sentence",
    "normalized_text",
    "answer",
    "正解",
    "正解テキスト",
    "本文",
    "台本",
    "元テキスト",
)
ID_COLUMN_CANDIDATES = (
    "id",
    "utt_id",
    "utterance_id",
    "sample_id",
    "name",
    "filename",
    "file",
)
COMMON_AUDIO_EXTENSIONS = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".mp4", ".webm")
COMMON_REFERENCE_EXTENSIONS = (".txt", ".text", ".md", ".markdown", ".srt", ".vtt")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CSV+audio または audio+reference directory から ASR 精度/速度ベンチマークを実行します。"
    )
    parser.add_argument("--csv", type=Path, default=None, help="評価対象CSV。未指定時は --reference-dir で同名ペアを作成")
    parser.add_argument("--audio-dir", type=Path, required=True, help="音声ファイルが入ったディレクトリ")
    parser.add_argument("--dataset-name", default=None, help="結果表示用データセット名。未指定時はCSV名")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["parakeet_ja"],
        help="モデルalias。例: parakeet_ja cohere_transcribe reazon_zipformer faster_whisper",
    )
    parser.add_argument("--language", default="ja", help="言語コード。日本語なら ja")
    parser.add_argument("--device", default="auto", help="cuda:0 / cpu / auto")
    parser.add_argument("--limit", type=int, default=None, help="先頭N件だけ実行")
    parser.add_argument("--log-every", type=int, default=20, help="進捗ログ間隔")
    parser.add_argument("--encoding", default="utf-8-sig", help="CSV文字コード")
    parser.add_argument("--audio-column", default=None, help="音声ファイル列名")
    parser.add_argument("--reference-column", default=None, help="正解テキスト列名")
    parser.add_argument("--id-column", default=None, help="ID列名。未指定なら連番")
    parser.add_argument(
        "--reference-dir",
        "--drafts-dir",
        type=Path,
        default=None,
        help="正解テキストディレクトリ。CSV列がファイル名の場合の起点、またはCSVなしの同名ペア評価で使用",
    )
    parser.add_argument(
        "--reference-extensions",
        nargs="+",
        default=list(COMMON_REFERENCE_EXTENSIONS),
        help="CSVなしモードで探す正解ファイル拡張子",
    )
    parser.add_argument(
        "--no-recursive-audio-search",
        action="store_true",
        help="音声ファイルの再帰検索を無効化",
    )
    parser.add_argument(
        "--skip-missing",
        action="store_true",
        help="音声や正解が欠けた行をエラーにせずスキップ",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="manifest.jsonl だけ作成してモデル推論は実行しない",
    )
    parser.add_argument(
        "--faster-whisper-size",
        default="medium",
        help="faster_whisper alias 用のモデルサイズ",
    )
    parser.add_argument("--qwen-max-new-tokens", type=int, default=2048)
    parser.add_argument("--qwen-max-inference-batch-size", type=int, default=8)
    parser.add_argument("--output-dir", type=Path, default=None, help="結果保存先")
    return parser.parse_args()


def _normalized_columns(fieldnames: list[str]) -> dict[str, str]:
    return {field.casefold(): field for field in fieldnames}


def select_column(
    fieldnames: list[str],
    explicit: str | None,
    candidates: tuple[str, ...],
    label: str,
) -> str:
    normalized = _normalized_columns(fieldnames)
    if explicit:
        if explicit in fieldnames:
            return explicit
        if explicit.casefold() in normalized:
            return normalized[explicit.casefold()]
        raise SystemExit(f"{label}列がCSVに見つかりません: {explicit}")

    for candidate in candidates:
        if candidate in fieldnames:
            return candidate
        if candidate.casefold() in normalized:
            return normalized[candidate.casefold()]

    raise SystemExit(
        f"{label}列を自動検出できません。--{label}-column で指定してください。"
        f" 利用可能な列: {', '.join(fieldnames)}"
    )


def read_csv_rows(path: Path, encoding: str) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise SystemExit(f"CSVヘッダーがありません: {path}")
        rows = [{key: (value or "") for key, value in row.items()} for row in reader]
    if not rows:
        raise SystemExit(f"CSVにデータ行がありません: {path}")
    return list(reader.fieldnames), rows


def build_audio_index(audio_dir: Path, recursive: bool) -> dict[str, list[Path]]:
    iterator = audio_dir.rglob("*") if recursive else audio_dir.glob("*")
    index: dict[str, list[Path]] = {}
    for path in iterator:
        if not path.is_file() or path.suffix.casefold() not in COMMON_AUDIO_EXTENSIONS:
            continue
        relative = path.relative_to(audio_dir).as_posix()
        keys = {path.name, path.stem, relative}
        for key in keys:
            index.setdefault(key, []).append(path)
    return index


def build_reference_index(reference_dir: Path, recursive: bool) -> dict[str, list[Path]]:
    iterator = reference_dir.rglob("*") if recursive else reference_dir.glob("*")
    index: dict[str, list[Path]] = {}
    for path in iterator:
        if not path.is_file():
            continue
        relative = path.relative_to(reference_dir).as_posix()
        keys = {path.name, path.stem, relative}
        for key in keys:
            index.setdefault(key, []).append(path)
    return index


def resolve_audio_path(raw_value: str, audio_dir: Path, audio_index: dict[str, list[Path]]) -> Path:
    value = raw_value.strip()
    if not value:
        raise ValueError("音声ファイル名が空です")

    direct = Path(value).expanduser()
    candidates: list[Path] = []
    if direct.is_absolute():
        candidates.append(direct)
    else:
        candidates.append(audio_dir / direct)

    if direct.suffix == "":
        for extension in COMMON_AUDIO_EXTENSIONS:
            candidates.append(audio_dir / f"{value}{extension}")

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    indexed_matches = audio_index.get(value) or audio_index.get(Path(value).name) or audio_index.get(Path(value).stem)
    if not indexed_matches:
        raise FileNotFoundError(f"音声が見つかりません: {raw_value}")
    unique_matches = sorted({path.resolve() for path in indexed_matches})
    if len(unique_matches) > 1:
        matches = ", ".join(str(path) for path in unique_matches[:5])
        raise ValueError(f"音声候補が複数あります: {raw_value} -> {matches}")
    return unique_matches[0]


def read_reference_text(raw_value: str, column_name: str, reference_dir: Path | None) -> str:
    value = raw_value.strip()
    if not value:
        raise ValueError("正解テキストが空です")

    candidate = Path(value).expanduser()
    possible_paths: list[Path] = []
    if candidate.is_absolute():
        possible_paths.append(candidate)
    elif reference_dir:
        possible_paths.append(reference_dir / candidate)

    looks_like_path = "path" in column_name.casefold() or candidate.suffix.casefold() in {".txt", ".text"}
    if looks_like_path:
        possible_paths.append(candidate)

    for path in possible_paths:
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return value


def resolve_reference_path_for_audio(
    audio_path: Path,
    audio_dir: Path,
    reference_dir: Path,
    reference_index: dict[str, list[Path]],
    reference_extensions: list[str],
) -> Path:
    relative_audio = audio_path.relative_to(audio_dir)
    candidates: list[Path] = [
        reference_dir / relative_audio,
        reference_dir / audio_path.name,
    ]
    for extension in reference_extensions:
        suffix = extension if extension.startswith(".") else f".{extension}"
        candidates.extend(
            [
                reference_dir / relative_audio.with_suffix(suffix),
                reference_dir / f"{audio_path.stem}{suffix}",
            ]
        )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    indexed_matches = (
        reference_index.get(relative_audio.as_posix())
        or reference_index.get(audio_path.name)
        or reference_index.get(audio_path.stem)
    )
    if not indexed_matches:
        raise FileNotFoundError(f"正解テキストが見つかりません: {audio_path.name}")
    unique_matches = sorted({path.resolve() for path in indexed_matches})
    if len(unique_matches) > 1:
        matches = ", ".join(str(path) for path in unique_matches[:5])
        raise ValueError(f"正解テキスト候補が複数あります: {audio_path.name} -> {matches}")
    return unique_matches[0]


def manifest_item_from_row(
    row: dict[str, str],
    row_number: int,
    audio_column: str,
    reference_column: str,
    id_column: str | None,
    audio_dir: Path,
    audio_index: dict[str, list[Path]],
    reference_dir: Path | None,
) -> dict[str, Any]:
    audio_path = resolve_audio_path(row.get(audio_column, ""), audio_dir, audio_index)
    reference_text = read_reference_text(row.get(reference_column, ""), reference_column, reference_dir)
    item_id = row.get(id_column, "").strip() if id_column else ""
    if not item_id:
        item_id = audio_path.stem or f"row_{row_number:06d}"
    return {
        "id": item_id,
        "audio_path": str(audio_path),
        "duration_s": ffprobe_duration(audio_path),
        "reference_text": reference_text,
        "source_row": row_number,
    }


def build_manifest_items(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not args.audio_dir.exists():
        raise SystemExit(f"音声ディレクトリが見つかりません: {args.audio_dir}")

    if args.csv is None:
        return build_manifest_items_from_directories(args)

    if not args.csv.exists():
        raise SystemExit(f"CSVが見つかりません: {args.csv}")

    fieldnames, rows = read_csv_rows(args.csv, args.encoding)
    audio_column = select_column(fieldnames, args.audio_column, AUDIO_COLUMN_CANDIDATES, "audio")
    reference_column = select_column(fieldnames, args.reference_column, REFERENCE_COLUMN_CANDIDATES, "reference")
    id_column = None
    if args.id_column or any(candidate in fieldnames for candidate in ID_COLUMN_CANDIDATES):
        id_column = select_column(fieldnames, args.id_column, ID_COLUMN_CANDIDATES, "id")

    audio_index = build_audio_index(
        args.audio_dir.resolve(),
        recursive=not args.no_recursive_audio_search,
    )

    items: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for row_number, row in enumerate(rows, start=2):
        if args.limit is not None and len(items) >= args.limit:
            break
        try:
            items.append(
                manifest_item_from_row(
                    row=row,
                    row_number=row_number,
                    audio_column=audio_column,
                    reference_column=reference_column,
                    id_column=id_column,
                    audio_dir=args.audio_dir.resolve(),
                    audio_index=audio_index,
                    reference_dir=args.reference_dir.resolve() if args.reference_dir else None,
                )
            )
        except Exception as exc:
            if not args.skip_missing:
                raise SystemExit(f"CSV {row_number}行目で失敗しました: {exc}") from exc
            skipped.append({"row": str(row_number), "reason": str(exc)})

    if not items:
        raise SystemExit("評価できる行がありません。CSV列と音声パスを確認してください。")

    metadata = {
        "csv": str(args.csv.resolve()),
        "audio_dir": str(args.audio_dir.resolve()),
        "audio_column": audio_column,
        "reference_column": reference_column,
        "id_column": id_column,
        "num_items": len(items),
        "num_skipped": len(skipped),
        "skipped": skipped,
    }
    return items, metadata


def build_manifest_items_from_directories(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if args.reference_dir is None:
        raise SystemExit("CSVなしで評価する場合は --reference-dir または --drafts-dir を指定してください。")
    if not args.reference_dir.exists():
        raise SystemExit(f"正解テキストディレクトリが見つかりません: {args.reference_dir}")

    audio_dir = args.audio_dir.resolve()
    reference_dir = args.reference_dir.resolve()
    recursive = not args.no_recursive_audio_search
    audio_paths = sorted(
        path.resolve()
        for path in (audio_dir.rglob("*") if recursive else audio_dir.glob("*"))
        if path.is_file() and path.suffix.casefold() in COMMON_AUDIO_EXTENSIONS
    )
    if not audio_paths:
        raise SystemExit(f"音声ファイルが見つかりません: {audio_dir}")

    reference_index = build_reference_index(reference_dir, recursive=recursive)
    items: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for audio_path in audio_paths:
        if args.limit is not None and len(items) >= args.limit:
            break
        try:
            reference_path = resolve_reference_path_for_audio(
                audio_path=audio_path,
                audio_dir=audio_dir,
                reference_dir=reference_dir,
                reference_index=reference_index,
                reference_extensions=args.reference_extensions,
            )
            reference_text = reference_path.read_text(encoding="utf-8").strip()
            if not reference_text:
                raise ValueError(f"正解テキストが空です: {reference_path}")
            items.append(
                {
                    "id": audio_path.stem,
                    "audio_path": str(audio_path),
                    "duration_s": ffprobe_duration(audio_path),
                    "reference_text": reference_text,
                    "reference_path": str(reference_path),
                }
            )
        except Exception as exc:
            if not args.skip_missing:
                raise SystemExit(f"{audio_path.name} のペア作成に失敗しました: {exc}") from exc
            skipped.append({"audio_path": str(audio_path), "reason": str(exc)})

    if not items:
        raise SystemExit("評価できる音声/正解テキストのペアがありません。")

    metadata = {
        "source": "paired_directories",
        "audio_dir": str(audio_dir),
        "reference_dir": str(reference_dir),
        "reference_extensions": args.reference_extensions,
        "num_audio_files": len(audio_paths),
        "num_items": len(items),
        "num_skipped": len(skipped),
        "skipped": skipped,
    }
    return items, metadata


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _percent(value: Any) -> str:
    if isinstance(value, (int, float)) and not math.isnan(float(value)):
        return f"{value * 100:.2f}%"
    return "n/a"


def write_summary_tables(reports: list[dict[str, Any]], output_root: Path) -> None:
    summary_csv = output_root / "summary.csv"
    fieldnames = [
        "model_alias",
        "num_items",
        "total_audio_s",
        "total_wall_s",
        "x_realtime",
        "real_time_factor",
        "one_hour_estimated_s",
        "one_hour_estimated_min",
        "cer_percent",
        "wer_percent",
        "gpu_memory_after_load_mb",
        "gpu_memory_after_run_mb",
        "torch_peak_reserved_mb",
    ]
    rows: list[dict[str, Any]] = []
    for report in reports:
        x_realtime = report.get("x_realtime")
        one_hour_s = 3600 / x_realtime if isinstance(x_realtime, (int, float)) and x_realtime > 0 else None
        metrics = report.get("reference_metrics") or {}
        rows.append(
            {
                "model_alias": report.get("model_alias"),
                "num_items": report.get("num_items"),
                "total_audio_s": round(float(report.get("total_audio_s") or 0.0), 3),
                "total_wall_s": round(float(report.get("total_wall_s") or 0.0), 3),
                "x_realtime": round(float(x_realtime), 3) if isinstance(x_realtime, (int, float)) else "",
                "real_time_factor": (
                    round(float(report["real_time_factor"]), 5)
                    if isinstance(report.get("real_time_factor"), (int, float))
                    else ""
                ),
                "one_hour_estimated_s": round(one_hour_s, 1) if one_hour_s else "",
                "one_hour_estimated_min": round(one_hour_s / 60, 2) if one_hour_s else "",
                "cer_percent": _percent(metrics.get("cer")),
                "wer_percent": _percent(metrics.get("wer")),
                "gpu_memory_after_load_mb": report.get("gpu_memory_after_load_mb"),
                "gpu_memory_after_run_mb": report.get("gpu_memory_after_run_mb"),
                "torch_peak_reserved_mb": report.get("torch_peak_reserved_mb"),
            }
        )

    with summary_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# ASR Benchmark Summary",
        "",
        "| model | items | CER | WER | xRealtime | 1h estimated | wall | audio |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        one_hour = f"{row['one_hour_estimated_min']} min" if row["one_hour_estimated_min"] != "" else "n/a"
        lines.append(
            "| {model_alias} | {num_items} | {cer_percent} | {wer_percent} | {x_realtime} | "
            "{one_hour} | {total_wall_s}s | {total_audio_s}s |".format(
                **row,
                one_hour=one_hour,
            )
        )
    (output_root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    dataset_name = args.dataset_name or (args.csv.stem if args.csv else args.audio_dir.stem)
    output_root = args.output_dir or (DEFAULT_OUTPUT_ROOT / now_stamp() / dataset_name)
    ensure_directory(output_root)

    items, metadata = build_manifest_items(args)
    manifest_path = output_root / "manifest.jsonl"
    write_jsonl(manifest_path, items)
    (output_root / "dataset_info.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total_audio_s = sum(float(item.get("duration_s") or 0.0) for item in items)
    print(f"manifest: {manifest_path}")
    print(f"items: {len(items)} audio={total_audio_s:.1f}s")
    if "audio_column" in metadata:
        print(f"columns: audio={metadata['audio_column']} reference={metadata['reference_column']}")
    else:
        print(f"paired dirs: audio={metadata['audio_dir']} reference={metadata['reference_dir']}")
    if metadata["num_skipped"]:
        print(f"skipped: {metadata['num_skipped']}")
    if args.dry_run:
        print(f"dry-run 完了: {output_root}")
        return

    device = resolve_device(args.device)
    benchmark_args = SimpleNamespace(
        dataset_name=dataset_name,
        language=args.language,
        device=args.device,
        limit=args.limit,
        log_every=args.log_every,
        faster_whisper_size=args.faster_whisper_size,
        qwen_max_new_tokens=args.qwen_max_new_tokens,
        qwen_max_inference_batch_size=args.qwen_max_inference_batch_size,
    )

    reports = []
    for model in resolve_models(args.models):
        reports.append(
            benchmark_dataset(
                items=items,
                model=model,
                args=benchmark_args,
                device=device,
                output_root=output_root,
            )
        )

    (output_root / "summary.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_summary_tables(reports, output_root)

    print(f"完了: {output_root}")
    for report in reports:
        metrics = report.get("reference_metrics") or {}
        print(
            f"- {report['model_alias']}: "
            f"xRealtime={report['x_realtime']:.2f} "
            f"CER={_percent(metrics.get('cer'))}"
        )


if __name__ == "__main__":
    main()
