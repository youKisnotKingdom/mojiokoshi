#!/usr/bin/env python3
"""
Hugging Face 上の日本語 ASR 評価データをローカル評価用に展開する。

出力:
  benchmark_datasets/<dataset_name>/
    - audio/*.wav
    - manifest.jsonl
    - dataset.json
"""
from __future__ import annotations

import argparse
import csv
import json
import tarfile
import tempfile
from pathlib import Path
from typing import Iterator

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download, list_repo_files

from benchmark_asr import DEFAULT_SAMPLE_RATE, ffprobe_duration, normalize_audio

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = ROOT / "benchmark_datasets"

DATASETS = {
    "jsut_basic5000_test": {
        "kind": "parquet_audio",
        "repo_id": "japanese-asr/ja_asr.jsut_basic5000",
        "repo_type": "dataset",
        "parquet_prefix": "data/test-",
    },
    "reazonspeech_test": {
        "kind": "parquet_audio",
        "repo_id": "japanese-asr/ja_asr.reazonspeech_test",
        "repo_type": "dataset",
        "parquet_prefix": "data/test-",
    },
    "fleurs_ja_test": {
        "kind": "fleurs_tsv_tar",
        "repo_id": "google/fleurs",
        "repo_type": "dataset",
        "tsv_path": "data/ja_jp/test.tsv",
        "audio_tar_path": "data/ja_jp/audio/test.tar.gz",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HF 評価データセットをローカル展開")
    parser.add_argument(
        "--dataset",
        required=True,
        choices=sorted(DATASETS),
        help="展開するデータセット alias",
    )
    parser.add_argument("--limit", type=int, default=None, help="先頭 N 件だけ展開")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="出力先ルート",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既存の wav を作り直す",
    )
    return parser.parse_args()


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def list_matching_repo_files(repo_id: str, repo_type: str, prefix: str) -> list[str]:
    files = list_repo_files(repo_id=repo_id, repo_type=repo_type)
    return sorted(file_name for file_name in files if file_name.startswith(prefix) and file_name.endswith(".parquet"))


def iter_parquet_rows(repo_id: str, repo_type: str, parquet_prefix: str) -> Iterator[dict]:
    parquet_files = list_matching_repo_files(repo_id=repo_id, repo_type=repo_type, prefix=parquet_prefix)
    if not parquet_files:
        raise SystemExit(f"parquet が見つかりません: {repo_id} {parquet_prefix}")

    for parquet_file in parquet_files:
        parquet_path = hf_hub_download(repo_id=repo_id, filename=parquet_file, repo_type=repo_type)
        parquet = pq.ParquetFile(parquet_path)
        for batch in parquet.iter_batches(batch_size=16, columns=["audio", "transcription"]):
            for row in batch.to_pylist():
                yield row


def dataset_item_id(dataset_name: str, source_name: str, index: int) -> str:
    stem = Path(source_name).stem.replace(" ", "_")
    return f"{dataset_name}-{index:05d}-{stem}"


def write_normalized_audio(raw_bytes: bytes, raw_name: str, output_path: Path, overwrite: bool) -> float:
    if output_path.exists() and not overwrite:
        return ffprobe_duration(output_path)

    ensure_directory(output_path.parent)
    suffix = Path(raw_name).suffix or ".bin"
    with tempfile.TemporaryDirectory(prefix="hf-audio-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        raw_path = temp_dir / f"source{suffix}"
        raw_path.write_bytes(raw_bytes)
        normalize_audio(raw_path, output_path, DEFAULT_SAMPLE_RATE)
    return ffprobe_duration(output_path)


def prepare_parquet_dataset(dataset_name: str, config: dict, output_dir: Path, limit: int | None, overwrite: bool) -> list[dict]:
    audio_dir = output_dir / "audio"
    ensure_directory(audio_dir)

    manifest: list[dict] = []
    for index, row in enumerate(
        iter_parquet_rows(
            repo_id=config["repo_id"],
            repo_type=config["repo_type"],
            parquet_prefix=config["parquet_prefix"],
        ),
        start=1,
    ):
        if limit is not None and len(manifest) >= limit:
            break

        audio = row["audio"]
        raw_name = audio.get("path") or f"{dataset_name}-{index:05d}.wav"
        item_id = dataset_item_id(dataset_name, raw_name, index)
        output_path = audio_dir / f"{item_id}.wav"
        duration_s = write_normalized_audio(
            raw_bytes=audio["bytes"],
            raw_name=raw_name,
            output_path=output_path,
            overwrite=overwrite,
        )
        manifest.append(
            {
                "id": item_id,
                "audio_path": str(output_path.resolve()),
                "reference_text": row["transcription"].strip(),
                "duration_s": duration_s,
                "source_name": raw_name,
            }
        )
        print(f"[{dataset_name}] prepared {len(manifest)}: {raw_name}")

    return manifest


def iter_fleurs_rows(tsv_path: Path) -> Iterator[tuple[int, str, str]]:
    with tsv_path.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for index, row in enumerate(reader, start=1):
            if len(row) < 4:
                continue
            yield index, row[1], row[3].replace(" ", "").strip()


def load_fleurs_tar_members(tar_path: Path) -> tuple[tarfile.TarFile, dict[str, tarfile.TarInfo]]:
    archive = tarfile.open(tar_path, "r:gz")
    members = {
        Path(member.name).name: member
        for member in archive.getmembers()
        if member.isfile()
    }
    return archive, members


def prepare_fleurs_dataset(dataset_name: str, config: dict, output_dir: Path, limit: int | None, overwrite: bool) -> list[dict]:
    audio_dir = output_dir / "audio"
    ensure_directory(audio_dir)

    tsv_path = Path(
        hf_hub_download(
            repo_id=config["repo_id"],
            filename=config["tsv_path"],
            repo_type=config["repo_type"],
        )
    )
    tar_path = Path(
        hf_hub_download(
            repo_id=config["repo_id"],
            filename=config["audio_tar_path"],
            repo_type=config["repo_type"],
        )
    )
    archive, member_map = load_fleurs_tar_members(tar_path)
    try:
        manifest: list[dict] = []
        for index, file_name, reference_text in iter_fleurs_rows(tsv_path):
            if limit is not None and len(manifest) >= limit:
                break

            member = member_map.get(file_name)
            if member is None:
                raise SystemExit(f"tar 内に音声が見つかりません: {file_name}")

            item_id = dataset_item_id(dataset_name, file_name, index)
            output_path = audio_dir / f"{item_id}.wav"
            if output_path.exists() and not overwrite:
                duration_s = ffprobe_duration(output_path)
            else:
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise SystemExit(f"tar から音声を読めません: {file_name}")
                raw_bytes = extracted.read()
                duration_s = write_normalized_audio(
                    raw_bytes=raw_bytes,
                    raw_name=file_name,
                    output_path=output_path,
                    overwrite=True,
                )

            manifest.append(
                {
                    "id": item_id,
                    "audio_path": str(output_path.resolve()),
                    "reference_text": reference_text,
                    "duration_s": duration_s,
                    "source_name": file_name,
                }
            )
            print(f"[{dataset_name}] prepared {len(manifest)}: {file_name}")
    finally:
        archive.close()

    return manifest


def write_manifest(output_dir: Path, dataset_name: str, manifest: list[dict], config: dict) -> None:
    manifest_path = output_dir / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as handle:
        for item in manifest:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    summary = {
        "dataset_name": dataset_name,
        "source_repo_id": config["repo_id"],
        "num_items": len(manifest),
        "total_audio_s": sum(item["duration_s"] for item in manifest),
        "manifest_path": str(manifest_path.resolve()),
    }
    (output_dir / "dataset.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    config = DATASETS[args.dataset]
    output_dir = args.output_root / args.dataset
    ensure_directory(output_dir)

    if config["kind"] == "parquet_audio":
        manifest = prepare_parquet_dataset(
            dataset_name=args.dataset,
            config=config,
            output_dir=output_dir,
            limit=args.limit,
            overwrite=args.overwrite,
        )
    elif config["kind"] == "fleurs_tsv_tar":
        manifest = prepare_fleurs_dataset(
            dataset_name=args.dataset,
            config=config,
            output_dir=output_dir,
            limit=args.limit,
            overwrite=args.overwrite,
        )
    else:
        raise SystemExit(f"未対応 dataset kind: {config['kind']}")

    write_manifest(output_dir=output_dir, dataset_name=args.dataset, manifest=manifest, config=config)
    print(f"完了: {output_dir}")
    print(f"件数: {len(manifest)}")


if __name__ == "__main__":
    main()
