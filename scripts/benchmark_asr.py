"""
ASR 検証用モデルの長尺ベンチマークスクリプト

例:
  python scripts/benchmark_asr.py \
    --audio /path/to/meeting.mp3 \
    --models faster_whisper qwen_asr parakeet_ja reazon_zipformer cohere_transcribe \
    --language ja \
    --device cuda \
    --chunk-seconds 300

出力:
  benchmarks/<timestamp>/<model_alias>/
    - transcript.txt
    - report.json

注意:
  - モデルごとに必要な Python パッケージが異なります。
  - 長尺比較の公平性を優先する場合は `--chunk-seconds 300` などで固定長分割してください。
  - モデル本来の長尺対応を確認したい場合は `--chunk-seconds 0` で丸ごと入力できます。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parent.parent / "config" / "asr_validation_models.json"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "benchmarks"
FALLBACK_FASTER_WHISPER_MODEL = "medium"
DEFAULT_SAMPLE_RATE = 16_000
MAX_PURE_PY_DISTANCE_PRODUCT = 5_000_000

LANGUAGE_CODE_TO_NAME = {
    "ja": "Japanese",
    "en": "English",
    "zh": "Chinese",
    "ko": "Korean",
}


@dataclass
class ChunkResult:
    index: int
    path: str
    audio_duration_s: float
    wall_time_s: float
    text: str


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=True)


def ffprobe_duration(audio_path: Path) -> float:
    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
    )
    return float(result.stdout.strip())


def parse_cuda_device_index(device: str) -> int | None:
    if not device.startswith("cuda"):
        return None
    if ":" not in device:
        return 0
    _prefix, suffix = device.split(":", 1)
    return int(suffix)


def query_gpu_memory_used_mb(device_index: int | None) -> int | None:
    if device_index is None:
        return None
    try:
        result = run_command(
            [
                "nvidia-smi",
                f"--id={device_index}",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ]
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    line = result.stdout.strip().splitlines()[0]
    return int(line)


def reset_torch_peak_memory(device_index: int | None) -> None:
    if device_index is None:
        return
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats(torch.device(f"cuda:{device_index}"))
    except (ImportError, RuntimeError, ValueError):
        return


def get_torch_peak_reserved_mb(device_index: int | None) -> int | None:
    if device_index is None:
        return None
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        peak_bytes = torch.cuda.max_memory_reserved(torch.device(f"cuda:{device_index}"))
        return int(peak_bytes / (1024 * 1024))
    except (ImportError, RuntimeError, ValueError):
        return None


def normalize_audio(source: Path, output_path: Path, sample_rate: int) -> Path:
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-vn",
            str(output_path),
        ]
    )
    return output_path


def split_audio(source: Path, output_dir: Path, chunk_seconds: int) -> list[Path]:
    if chunk_seconds <= 0:
        single_path = output_dir / "chunk_0000.wav"
        shutil.copy2(source, single_path)
        return [single_path]

    pattern = output_dir / "chunk_%04d.wav"
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-f",
            "segment",
            "-segment_time",
            str(chunk_seconds),
            "-c",
            "copy",
            "-reset_timestamps",
            "1",
            str(pattern),
        ]
    )
    chunks = sorted(output_dir.glob("chunk_*.wav"))
    if not chunks:
        raise RuntimeError("音声分割に失敗しました。ffmpeg の出力を確認してください。")
    return chunks


def load_catalog() -> dict[str, dict[str, Any]]:
    with CATALOG_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    catalog = {item["alias"]: item for item in data["models"]}
    catalog["faster_whisper"] = {
        "alias": "faster_whisper",
        "repo_id": FALLBACK_FASTER_WHISPER_MODEL,
        "family": "faster-whisper",
        "runtime": "faster-whisper",
        "summary": "既存アプリで使っている Faster Whisper ベースライン。",
    }
    return catalog


def resolve_cached_model_source(repo_id: str) -> str:
    if "/" not in repo_id:
        return repo_id

    cache_roots: list[Path] = []
    for env_name in ("HF_HOME", "TRANSFORMERS_CACHE"):
        env_value = os.environ.get(env_name)
        if not env_value:
            continue
        env_path = Path(env_value).expanduser()
        cache_roots.extend([env_path, env_path / "hub"])

    default_cache_root = Path.home() / ".cache" / "huggingface"
    cache_roots.extend([default_cache_root, default_cache_root / "hub"])

    seen: set[Path] = set()
    normalized_roots: list[Path] = []
    for candidate in cache_roots:
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized_roots.append(candidate)

    repo_cache_dir_name = f"models--{repo_id.replace('/', '--')}"
    for root in normalized_roots:
        snapshots_dir = root / repo_cache_dir_name / "snapshots"
        if not snapshots_dir.exists():
            continue

        snapshots = sorted(
            (path for path in snapshots_dir.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if snapshots:
            return str(snapshots[0])

    return repo_id


def resolve_models(requested_models: list[str]) -> list[dict[str, Any]]:
    catalog = load_catalog()
    missing = [name for name in requested_models if name not in catalog]
    if missing:
        available = ", ".join(sorted(catalog))
        raise SystemExit(f"未登録のモデル alias です: {', '.join(missing)}\n利用可能: {available}")
    return [catalog[name] for name in requested_models]


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def compute_edit_distance(a: list[str], b: list[str]) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous = list(range(len(b) + 1))
    for i, token_a in enumerate(a, start=1):
        current = [i]
        for j, token_b in enumerate(b, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (token_a != token_b)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def levenshtein_distance(sequence_a: list[str], sequence_b: list[str]) -> tuple[int, str]:
    try:
        from rapidfuzz.distance import Levenshtein

        return Levenshtein.distance(sequence_a, sequence_b), "rapidfuzz"
    except ImportError:
        size_product = len(sequence_a) * len(sequence_b)
        if size_product > MAX_PURE_PY_DISTANCE_PRODUCT:
            raise RuntimeError(
                "reference/hypothesis が長すぎるため、pure Python の編集距離計算をスキップしました。 "
                "rapidfuzz を入れるか、短いチャンク単位で評価してください。"
            )
        return compute_edit_distance(sequence_a, sequence_b), "python"


def compute_error_rates(reference_text: str, hypothesis_text: str) -> dict[str, float | str | None] | None:
    reference_text = reference_text.strip()
    hypothesis_text = hypothesis_text.strip()
    if not reference_text:
        return None

    try:
        cer_distance, cer_method = levenshtein_distance(list(reference_text), list(hypothesis_text))
    except RuntimeError as exc:
        return {
            "cer": None,
            "wer": None,
            "method": "skipped",
            "skipped_reason": str(exc),
        }

    cer = cer_distance / max(1, len(reference_text))
    reference_words = reference_text.split()
    hypothesis_words = hypothesis_text.split()
    wer_distance, wer_method = levenshtein_distance(reference_words, hypothesis_words)
    wer = wer_distance / max(1, len(reference_words))
    return {
        "cer": cer,
        "wer": wer,
        "method": cer_method if cer_method == wer_method else f"cer:{cer_method},wer:{wer_method}",
    }


def resolve_device(preferred: str) -> str:
    if preferred != "auto":
        return preferred

    try:
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def build_adapter(
    model_alias: str,
    repo_id: str,
    device: str,
    faster_whisper_size: str,
    family: str | None = None,
    language: str | None = None,
):
    if model_alias == "faster_whisper":
        return FasterWhisperAdapter(faster_whisper_size, device)
    if family == "qwen3-asr" or model_alias == "qwen_asr":
        return QwenAsrAdapter(
            repo_id,
            device,
            max_new_tokens=build_adapter.qwen_max_new_tokens,
            max_inference_batch_size=build_adapter.qwen_max_inference_batch_size,
        )
    if model_alias == "cohere_transcribe":
        return CohereTranscribeAdapter(repo_id, device)
    if family in {"zipformer", "hubert-k2"} or model_alias in {"reazon_zipformer", "reazon_hubert_k2"}:
        return ReazonZipformerAdapter(repo_id, device)
    if family == "nemo-rnnt" or model_alias == "reazon_nemo_v2":
        return ReazonNemoAdapter(repo_id, device)
    if model_alias == "parakeet_ja":
        return ParakeetAdapter(repo_id, device)
    if family == "canary" or model_alias == "canary_1b_flash":
        source_lang = (language or "ja").split("-")[0]
        if source_lang not in CanaryAdapter.SUPPORTED_LANGS:
            supported = ", ".join(sorted(CanaryAdapter.SUPPORTED_LANGS))
            raise SystemExit(
                f"Canary の公開 checkpoint は {supported} のみ対応です。"
                f" 指定言語 `{source_lang}` はローカル実行対象外です。"
            )
        return CanaryAdapter(repo_id, device)
    raise SystemExit(f"未対応のベンチマークアダプタです: {model_alias}")


class FasterWhisperAdapter:
    def __init__(self, model_size: str, device: str) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise SystemExit("faster-whisper が見つかりません。`pip install faster-whisper` を実行してください。") from exc

        whisper_device = "cuda" if device.startswith("cuda") else "cpu"
        compute_type = "float16" if whisper_device == "cuda" else "int8"
        self.model = WhisperModel(model_size, device=whisper_device, compute_type=compute_type)

    def transcribe(self, audio_path: Path, language: str | None) -> str:
        segments, _info = self.model.transcribe(str(audio_path), language=language or None, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments if segment.text.strip())


class QwenAsrAdapter:
    def __init__(
        self,
        repo_id: str,
        device: str,
        max_new_tokens: int,
        max_inference_batch_size: int,
    ) -> None:
        try:
            import torch
            from qwen_asr import Qwen3ASRModel
        except ImportError as exc:
            raise SystemExit(
                "qwen-asr が見つかりません。`pip install -U qwen-asr` を別環境で実行してください。"
            ) from exc

        dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
        model_source = resolve_cached_model_source(repo_id)
        self.model = Qwen3ASRModel.from_pretrained(
            model_source,
            dtype=dtype,
            device_map=device,
            max_inference_batch_size=max_inference_batch_size,
            max_new_tokens=max_new_tokens,
        )

    def transcribe(self, audio_path: Path, language: str | None) -> str:
        language_name = LANGUAGE_CODE_TO_NAME.get(language or "", None)
        results = self.model.transcribe(audio=str(audio_path), language=language_name)
        return results[0].text.strip()


class CohereTranscribeAdapter:
    def __init__(self, repo_id: str, device: str) -> None:
        try:
            import torch
            from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
        except ImportError as exc:
            raise SystemExit(
                "Cohere 用に transformers / torch が必要です。公式推奨の依存を別環境へ入れてください。"
            ) from exc

        model_source = resolve_cached_model_source(repo_id)
        torch_dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
        self.processor = AutoProcessor.from_pretrained(model_source, trust_remote_code=True)
        self.model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_source,
            trust_remote_code=True,
            torch_dtype=torch_dtype,
        ).to(device)
        self.model.eval()

    def transcribe(self, audio_path: Path, language: str | None) -> str:
        texts = self.model.transcribe(
            processor=self.processor,
            audio_files=[str(audio_path)],
            language=language or None,
        )
        return texts[0].strip()


class ReazonZipformerAdapter:
    def __init__(self, repo_id: str, device: str) -> None:
        try:
            import torch
            from transformers import AutoModelForCTC, AutoProcessor
        except ImportError as exc:
            raise SystemExit(
                "Reazon 用に transformers / torch が必要です。公式サンプルに沿って別環境を用意してください。"
            ) from exc

        self.device = device
        model_source = resolve_cached_model_source(repo_id)
        self.processor = AutoProcessor.from_pretrained(model_source)
        self.model = AutoModelForCTC.from_pretrained(
            model_source,
            trust_remote_code=True,
        ).to(device)
        self.model.eval()

    def transcribe(self, audio_path: Path, language: str | None) -> str:
        try:
            import librosa
            import numpy as np
            import torch
        except ImportError as exc:
            raise SystemExit(
                "Reazon 用に librosa / numpy / torch が必要です。公式サンプルに沿って依存を追加してください。"
            ) from exc

        audio, _ = librosa.load(str(audio_path), sr=DEFAULT_SAMPLE_RATE)
        audio = np.pad(audio, pad_width=int(0.5 * DEFAULT_SAMPLE_RATE))
        input_values = self.processor(
            audio,
            return_tensors="pt",
            sampling_rate=DEFAULT_SAMPLE_RATE,
        ).input_values
        input_values = input_values.to(self.device)
        with torch.inference_mode():
            logits = self.model(input_values).logits.cpu()
        predicted_ids = torch.argmax(logits, dim=-1)[0]
        return self.processor.decode(predicted_ids, skip_special_tokens=True).removeprefix("▁").strip()


class ReazonNemoAdapter:
    def __init__(self, repo_id: str, device: str) -> None:
        try:
            from nemo.collections.asr.models import EncDecRNNTBPEModel
        except ImportError as exc:
            raise SystemExit(
                "Reazon NeMo 用に nemo_toolkit['asr'] が必要です。別環境へインストールしてください。"
            ) from exc

        model_source = Path(resolve_cached_model_source(repo_id))
        checkpoint_path = model_source
        if model_source.is_dir():
            nemo_files = sorted(model_source.glob("*.nemo"))
            if not nemo_files:
                raise SystemExit(f"Reazon NeMo の checkpoint が見つかりません: {model_source}")
            checkpoint_path = nemo_files[0]

        map_location = "cuda" if device.startswith("cuda") else "cpu"
        self.model = EncDecRNNTBPEModel.restore_from(str(checkpoint_path), map_location=map_location)
        self.model.eval()

    def transcribe(self, audio_path: Path, language: str | None) -> str:
        try:
            from reazonspeech.nemo.asr import audio_from_path, transcribe
        except ImportError as exc:
            raise SystemExit(
                "Reazon NeMo ランタイムが見つかりません。`reazonspeech-nemo-asr` をインストールしてください。"
            ) from exc

        result = transcribe(self.model, audio_from_path(str(audio_path)))
        return result.text.strip()


class ParakeetAdapter:
    def __init__(self, repo_id: str, device: str) -> None:
        try:
            import nemo.collections.asr as nemo_asr
        except ImportError as exc:
            raise SystemExit(
                "Parakeet 用に nemo_toolkit['asr'] が必要です。別環境へインストールしてください。"
            ) from exc

        self.model = nemo_asr.models.ASRModel.from_pretrained(model_name=repo_id)
        if device.startswith("cuda"):
            self.model = self.model.cuda()

    def transcribe(self, audio_path: Path, language: str | None) -> str:
        result = self.model.transcribe([str(audio_path)])
        item = result[0]
        return getattr(item, "text", str(item)).strip()


class CanaryAdapter:
    SUPPORTED_LANGS = {"en", "de", "es", "fr"}

    def __init__(self, repo_id: str, device: str) -> None:
        try:
            import nemo.collections.asr as nemo_asr
        except ImportError as exc:
            raise SystemExit(
                "Canary 用に nemo_toolkit['asr'] が必要です。別環境へインストールしてください。"
            ) from exc

        self.model = nemo_asr.models.EncDecMultiTaskModel.from_pretrained(model_name=repo_id)
        decode_cfg = self.model.cfg.decoding
        decode_cfg.beam.beam_size = 1
        self.model.change_decoding_strategy(decode_cfg)
        if device.startswith("cuda"):
            self.model = self.model.cuda()

    def transcribe(self, audio_path: Path, language: str | None) -> str:
        source_lang = (language or "ja").split("-")[0]
        if source_lang not in self.SUPPORTED_LANGS:
            supported = ", ".join(sorted(self.SUPPORTED_LANGS))
            raise SystemExit(
                f"Canary の公開 checkpoint は {supported} のみ対応です。"
                f" 指定言語 `{source_lang}` はローカル実行対象外です。"
            )
        target_lang = source_lang
        with tempfile.TemporaryDirectory(prefix="canary-manifest-") as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            manifest_path = temp_dir / "input_manifest.jsonl"
            manifest_item = {
                "audio_filepath": str(audio_path),
                "duration": None,
                "taskname": "asr",
                "source_lang": source_lang,
                "target_lang": target_lang,
                "pnc": "yes",
                "answer": "na",
            }
            manifest_path.write_text(json.dumps(manifest_item, ensure_ascii=False) + "\n", encoding="utf-8")
            output = self.model.transcribe(str(manifest_path), batch_size=1)
        item = output[0]
        return getattr(item, "text", str(item)).strip()


def benchmark_model(
    adapter,
    model_alias: str,
    repo_id: str,
    chunks: list[Path],
    language: str | None,
    output_dir: Path,
    reference_text: str | None,
) -> dict[str, Any]:
    ensure_directory(output_dir)

    chunk_results: list[ChunkResult] = []
    transcript_parts: list[str] = []
    wall_started = time.perf_counter()

    for index, chunk_path in enumerate(chunks):
        audio_duration_s = ffprobe_duration(chunk_path)
        started = time.perf_counter()
        text = adapter.transcribe(chunk_path, language)
        wall_time_s = time.perf_counter() - started
        transcript_parts.append(text)
        chunk_results.append(
            ChunkResult(
                index=index,
                path=str(chunk_path),
                audio_duration_s=audio_duration_s,
                wall_time_s=wall_time_s,
                text=text,
            )
        )
        print(
            f"[{model_alias}] chunk={index + 1}/{len(chunks)} "
            f"audio={audio_duration_s:.1f}s wall={wall_time_s:.1f}s"
        )

    total_wall_s = time.perf_counter() - wall_started
    transcript = "\n".join(part for part in transcript_parts if part).strip()
    total_audio_s = sum(item.audio_duration_s for item in chunk_results)
    rtf = total_wall_s / total_audio_s if total_audio_s > 0 else math.nan
    throughput = total_audio_s / total_wall_s if total_wall_s > 0 else math.nan

    errors = compute_error_rates(reference_text or "", transcript) if reference_text else None
    report = {
        "model_alias": model_alias,
        "repo_id": repo_id,
        "language": language,
        "num_chunks": len(chunk_results),
        "total_audio_s": total_audio_s,
        "total_wall_s": total_wall_s,
        "real_time_factor": rtf,
        "x_realtime": throughput,
        "reference_metrics": errors,
        "chunks": [asdict(item) for item in chunk_results],
    }

    (output_dir / "transcript.txt").write_text(f"{transcript}\n", encoding="utf-8")
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ASR 検証用モデルの長尺ベンチマーク")
    parser.add_argument("--audio", type=Path, required=True, help="評価対象の音声ファイル")
    parser.add_argument(
        "--models",
        nargs="+",
        required=True,
        help="ベンチマーク対象の model alias。例: faster_whisper qwen_asr",
    )
    parser.add_argument("--language", default="ja", help="言語コード。例: ja, en。空なら自動検出")
    parser.add_argument("--device", default="auto", help="cuda:0 / cpu / auto")
    parser.add_argument(
        "--chunk-seconds",
        type=int,
        default=300,
        help="固定長分割の秒数。0 を指定すると分割せず丸ごと処理",
    )
    parser.add_argument(
        "--faster-whisper-size",
        default=FALLBACK_FASTER_WHISPER_MODEL,
        help="faster_whisper alias 用のモデルサイズ",
    )
    parser.add_argument(
        "--qwen-max-new-tokens",
        type=int,
        default=4096,
        help="Qwen3-ASR 用の max_new_tokens。長尺では大きめにする。",
    )
    parser.add_argument(
        "--qwen-max-inference-batch-size",
        type=int,
        default=8,
        help="Qwen3-ASR 用の max_inference_batch_size。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="結果保存先。未指定時は benchmarks/<timestamp>",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=None,
        help="正解テキスト。指定すると CER/WER を計算",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_adapter.qwen_max_new_tokens = args.qwen_max_new_tokens
    build_adapter.qwen_max_inference_batch_size = args.qwen_max_inference_batch_size
    if not args.audio.exists():
        raise SystemExit(f"音声ファイルが見つかりません: {args.audio}")

    requested_models = resolve_models(args.models)
    device = resolve_device(args.device)
    output_root = args.output_dir or (DEFAULT_OUTPUT_ROOT / now_stamp())
    ensure_directory(output_root)

    reference_text = None
    if args.reference:
        reference_text = args.reference.read_text(encoding="utf-8")

    summary: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="asr-benchmark-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        normalized_path = temp_dir / "normalized.wav"
        normalize_audio(args.audio, normalized_path, DEFAULT_SAMPLE_RATE)
        chunks_dir = temp_dir / "chunks"
        ensure_directory(chunks_dir)
        chunks = split_audio(normalized_path, chunks_dir, args.chunk_seconds)

        print(f"入力音声: {args.audio}")
        print(f"正規化後: {normalized_path}")
        print(f"チャンク数: {len(chunks)}")
        print(f"実行デバイス: {device}")
        print()

        for model in requested_models:
            adapter = build_adapter(
                model_alias=model["alias"],
                repo_id=model["repo_id"],
                device=device,
                faster_whisper_size=args.faster_whisper_size,
                family=model.get("family"),
                language=args.language or None,
            )
            model_output_dir = output_root / model["alias"]
            device_index = parse_cuda_device_index(device)
            gpu_memory_after_load_mb = query_gpu_memory_used_mb(device_index)
            reset_torch_peak_memory(device_index)
            report = benchmark_model(
                adapter=adapter,
                model_alias=model["alias"],
                repo_id=model["repo_id"],
                chunks=chunks,
                language=args.language or None,
                output_dir=model_output_dir,
                reference_text=reference_text,
            )
            report["gpu_memory_after_load_mb"] = gpu_memory_after_load_mb
            report["gpu_memory_after_run_mb"] = query_gpu_memory_used_mb(device_index)
            report["torch_peak_reserved_mb"] = get_torch_peak_reserved_mb(device_index)
            (model_output_dir / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            summary.append(report)

    summary_path = output_root / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("ベンチマーク完了")
    print(f"結果保存先: {output_root}")
    for report in summary:
        print(
            f"- {report['model_alias']}: "
            f"RTF={report['real_time_factor']:.3f}, "
            f"xRealtime={report['x_realtime']:.2f}, "
            f"audio={report['total_audio_s']:.1f}s, "
            f"wall={report['total_wall_s']:.1f}s"
        )


if __name__ == "__main__":
    main()
