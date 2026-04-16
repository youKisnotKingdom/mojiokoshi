"""
ASR 検証用モデルのダウンロードスクリプト

使い方:
  # 登録モデルを一覧表示
  python scripts/download_validation_models.py --list

  # すべての検証用モデルをダウンロード
  python scripts/download_validation_models.py

  # 一部のモデルだけをダウンロード
  python scripts/download_validation_models.py --only qwen_asr reazon_zipformer

環境変数:
  HF_HOME                Hugging Face キャッシュ保存先（例: /app/models）
  HF_TOKEN               Hugging Face アクセストークン（gated model 用）
  VALIDATION_MODELS      カンマ区切りの alias または repo_id
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "config" / "asr_validation_models.json"


def load_catalog(manifest_path: Path) -> list[dict]:
    with manifest_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data["models"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ASR 検証用モデルの取得")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST_PATH,
        help="モデル定義 JSON のパス",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="登録済みモデルを表示して終了",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        default=None,
        help="取得対象の alias または repo_id を指定",
    )
    return parser.parse_args()


def get_selectors(args: argparse.Namespace) -> list[str] | None:
    if args.only:
        return args.only
    raw = os.environ.get("VALIDATION_MODELS", "").strip()
    if not raw:
        return None
    return [item.strip() for item in raw.split(",") if item.strip()]


def select_models(models: list[dict], selectors: list[str] | None) -> list[dict]:
    if not selectors:
        return models

    selected = []
    remaining = set(selectors)
    for model in models:
        if model["alias"] in remaining or model["repo_id"] in remaining:
            selected.append(model)
            remaining.discard(model["alias"])
            remaining.discard(model["repo_id"])

    if remaining:
        available = ", ".join(model["alias"] for model in models)
        raise SystemExit(f"未登録のモデル指定があります: {', '.join(sorted(remaining))}\n利用可能: {available}")

    return selected


def print_catalog(models: list[dict]) -> None:
    print("登録済み ASR 検証用モデル:")
    print()
    for model in models:
        print(f"- {model['alias']}")
        print(f"  repo: {model['repo_id']}")
        print(f"  family: {model['family']}")
        print(f"  size: {model['parameters']}")
        print(f"  runtime: {model['runtime']}")
        print(f"  access: {model['access']}")
        print(f"  summary: {model['summary']}")
        for note in model.get("notes", []):
            print(f"  note: {note}")
        print()


def download_model(model: dict) -> str:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit(
            "huggingface_hub が見つかりません。`pip install -r requirements.txt` を実行してください。"
        ) from exc

    kwargs = {
        "repo_id": model["repo_id"],
        "repo_type": "model",
        "resume_download": True,
    }
    allow_patterns = model.get("allow_patterns")
    if allow_patterns:
        kwargs["allow_patterns"] = allow_patterns
    cache_dir = os.environ.get("HF_HOME")
    if cache_dir:
        kwargs["cache_dir"] = cache_dir

    token = os.environ.get("HF_TOKEN")
    if token:
        kwargs["token"] = token

    return snapshot_download(**kwargs)


def main() -> None:
    args = parse_args()
    models = load_catalog(args.manifest)

    if args.list:
        print_catalog(models)
        return

    selected_models = select_models(models, get_selectors(args))
    print(f"保存先: {os.environ.get('HF_HOME', '~/.cache/huggingface')}")
    print(f"対象モデル数: {len(selected_models)}")
    print()

    for model in selected_models:
        print(f"ダウンロード開始: {model['alias']} ({model['repo_id']})")
        try:
            path = download_model(model)
        except Exception as exc:
            print(f"失敗: {model['repo_id']} -> {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"完了: {path}")
        print()


if __name__ == "__main__":
    main()
