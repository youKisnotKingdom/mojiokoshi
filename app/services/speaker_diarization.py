"""Speaker diarization helpers for post-processing transcription output."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_speaker_diarization_pipelines: dict[str, Any] = {}


def _resolve_source() -> str:
    if settings.speaker_diarization_model_path:
        return settings.speaker_diarization_model_path
    return settings.speaker_diarization_model_id


def _resolve_pipeline_device() -> str:
    device = settings.speaker_diarization_device
    if device != "auto":
        return device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def get_speaker_diarization_pipeline():
    """Load and cache the pyannote speaker diarization pipeline."""
    source = _resolve_source()
    runtime_device = _resolve_pipeline_device()
    cache_key = f"{source}:{runtime_device}"
    if cache_key in _speaker_diarization_pipelines:
        return _speaker_diarization_pipelines[cache_key]

    try:
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise RuntimeError(
            "Speaker diarization requires pyannote.audio. Rebuild the app image after installing dependencies."
        ) from exc

    load_kwargs: dict[str, str] = {}
    if not Path(source).exists() and settings.huggingface_token:
        load_kwargs["token"] = settings.huggingface_token

    pipeline = Pipeline.from_pretrained(source, **load_kwargs)
    if runtime_device.startswith("cuda"):
        import torch

        pipeline.to(torch.device("cuda"))

    _speaker_diarization_pipelines[cache_key] = pipeline
    logger.info("Loaded speaker diarization pipeline %s on %s", source, runtime_device)
    return pipeline


def diarize_audio(audio_path: str) -> list[dict[str, float | str]]:
    """Run speaker diarization and return exclusive speaker turns."""
    pipeline = get_speaker_diarization_pipeline()

    kwargs: dict[str, int] = {}
    if settings.speaker_diarization_min_speakers > 0:
        kwargs["min_speakers"] = settings.speaker_diarization_min_speakers
    if settings.speaker_diarization_max_speakers > 0:
        kwargs["max_speakers"] = settings.speaker_diarization_max_speakers

    output = pipeline(audio_path, **kwargs)
    annotation = (
        getattr(output, "exclusive_speaker_diarization", None)
        or getattr(output, "speaker_diarization", None)
        or output
    )

    speaker_turns: list[dict[str, float | str]] = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        speaker_turns.append(
            {
                "speaker": str(speaker),
                "start": float(turn.start),
                "end": float(turn.end),
            }
        )

    return speaker_turns


def _segment_overlap(start: float, end: float, turn: dict[str, float | str]) -> float:
    return max(0.0, min(end, float(turn["end"])) - max(start, float(turn["start"])))


def assign_speakers_to_segments(
    segments: list[dict[str, Any]],
    speaker_turns: list[dict[str, float | str]],
) -> list[dict[str, Any]]:
    """Attach best-overlap speaker labels to transcription segments."""
    if not speaker_turns:
        return segments

    labelled_segments: list[dict[str, Any]] = []
    last_speaker: str | None = None

    for segment in segments:
        start = float(segment.get("start", 0.0) or 0.0)
        end = float(segment.get("end", start) or start)
        best_turn = None
        best_overlap = 0.0

        for turn in speaker_turns:
            overlap = _segment_overlap(start, end, turn)
            if overlap > best_overlap:
                best_overlap = overlap
                best_turn = turn

        speaker = None
        if best_turn is not None and best_overlap > 0:
            speaker = str(best_turn["speaker"])
        elif last_speaker is not None:
            speaker = last_speaker

        labelled_segment = dict(segment)
        if speaker is not None:
            labelled_segment["speaker"] = speaker
            last_speaker = speaker
        labelled_segments.append(labelled_segment)

    return labelled_segments


def build_speaker_blocks(segments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Collapse consecutive speaker-labelled segments into display blocks."""
    if not segments:
        return []

    blocks: list[dict[str, Any]] = []
    current_block: dict[str, Any] | None = None

    for segment in segments:
        text = str(segment.get("text", "")).strip()
        speaker = segment.get("speaker")
        if not text or not speaker:
            continue

        start = float(segment.get("start", 0.0) or 0.0)
        end = float(segment.get("end", start) or start)

        if current_block and current_block["speaker"] == speaker:
            current_block["text"] = f"{current_block['text']} {text}".strip()
            current_block["end"] = end
            continue

        current_block = {
            "speaker": speaker,
            "text": text,
            "start": start,
            "end": end,
        }
        blocks.append(current_block)

    return blocks
