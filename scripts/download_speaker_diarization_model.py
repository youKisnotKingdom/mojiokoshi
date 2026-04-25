#!/usr/bin/env python3
"""Download the pyannote speaker diarization model for offline deployment."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


DEFAULT_MODEL_ID = "pyannote/speaker-diarization-community-1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a pyannote speaker diarization model for offline use."
    )
    parser.add_argument(
        "--model-id",
        default=DEFAULT_MODEL_ID,
        help=f"Hugging Face model id (default: {DEFAULT_MODEL_ID})",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where the model snapshot will be stored.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        from huggingface_hub import get_token, snapshot_download
    except ImportError:
        print(
            "huggingface_hub is not installed. Activate the project venv and install requirements first.",
            file=sys.stderr,
        )
        return 1

    token = os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HF_TOKEN") or get_token()
    if not token:
        print(
            "Hugging Face authentication is required. "
            "Run `hf auth login` or set HUGGINGFACE_TOKEN after accepting the model conditions.",
            file=sys.stderr,
        )
        return 1

    snapshot_download(
        repo_id=args.model_id,
        token=token,
        local_dir=str(output_dir),
        local_dir_use_symlinks=False,
    )

    print(f"Downloaded {args.model_id} to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
