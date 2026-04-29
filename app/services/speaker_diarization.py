"""Speaker diarization helpers for post-processing transcription output."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_speaker_diarization_pipelines: dict[str, Any] = {}
MIN_DISPLAY_TURN_SECONDS = 1.2


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


def _best_speaker(
    start: float,
    end: float,
    speaker_turns: list[dict[str, float | str]],
    fallback: str | None = None,
) -> str | None:
    best_turn = None
    best_overlap = 0.0
    nearest_turn = None
    nearest_gap = float("inf")
    for turn in speaker_turns:
        overlap = _segment_overlap(start, end, turn)
        if overlap > best_overlap:
            best_overlap = overlap
            best_turn = turn
        turn_start = float(turn["start"])
        turn_end = float(turn["end"])
        if end < turn_start:
            gap = turn_start - end
        elif start > turn_end:
            gap = start - turn_end
        else:
            gap = 0.0
        if gap < nearest_gap:
            nearest_gap = gap
            nearest_turn = turn

    if best_turn is not None and best_overlap > 0:
        return str(best_turn["speaker"])
    if nearest_turn is not None and nearest_gap <= 1.0:
        return str(nearest_turn["speaker"])
    return fallback


def _overlapping_turns(
    start: float,
    end: float,
    speaker_turns: list[dict[str, float | str]],
) -> list[dict[str, float | str]]:
    turns: list[dict[str, float | str]] = []
    segment_duration = max(0.0, end - start)
    min_turn_duration = min(
        MIN_DISPLAY_TURN_SECONDS,
        max(0.35, segment_duration * 0.04),
    )
    for turn in speaker_turns:
        overlap_start = max(start, float(turn["start"]))
        overlap_end = min(end, float(turn["end"]))
        if overlap_end <= overlap_start:
            continue
        if overlap_end - overlap_start < min_turn_duration:
            continue

        speaker = str(turn["speaker"])
        if turns and turns[-1]["speaker"] == speaker:
            turns[-1]["end"] = overlap_end
            continue

        turns.append(
            {
                "speaker": speaker,
                "start": overlap_start,
                "end": overlap_end,
            }
        )
    return turns


def _split_text_by_turns(
    text: str,
    turns: list[dict[str, float | str]],
) -> list[str]:
    if len(turns) <= 1:
        return [text]

    text = text.strip()
    if not text:
        return ["" for _ in turns]

    total_duration = sum(float(turn["end"]) - float(turn["start"]) for turn in turns)
    if total_duration <= 0:
        return [text] + ["" for _ in turns[1:]]

    pieces: list[str] = []
    cursor = 0
    length = len(text)
    for index, turn in enumerate(turns):
        if index == len(turns) - 1:
            pieces.append(text[cursor:].strip())
            break

        duration = float(turn["end"]) - float(turn["start"])
        target = cursor + round((length - cursor) * duration / total_duration)
        target = max(cursor + 1, min(length - 1, target))

        # Prefer natural Japanese punctuation near the proportional split point.
        search_start = max(cursor + 1, target - 12)
        search_end = min(length - 1, target + 12)
        punctuation = "。！？、,. "
        candidates = [
            pos + 1
            for pos in range(search_start, search_end)
            if text[pos] in punctuation
        ]
        if candidates:
            target = min(candidates, key=lambda pos: abs(pos - target))

        pieces.append(text[cursor:target].strip())
        cursor = target

    return pieces


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
        words = segment.get("words") or []

        if isinstance(words, list) and len(words) > 1:
            current_segment: dict[str, Any] | None = None
            for word in words:
                word_text = str(word.get("word", "")).strip()
                if not word_text:
                    continue

                word_start = float(word.get("start", start) or start)
                word_end = float(word.get("end", word_start) or word_start)
                speaker = _best_speaker(word_start, word_end, speaker_turns, last_speaker)
                if current_segment and current_segment.get("speaker") == speaker:
                    current_segment["text"] = f"{current_segment['text']}{word_text}".strip()
                    current_segment["end"] = word_end
                    current_segment["words"].append(word)
                    continue

                if current_segment:
                    labelled_segments.append(current_segment)

                current_segment = {
                    "text": word_text,
                    "start": word_start,
                    "end": word_end,
                    "words": [word],
                }
                if speaker is not None:
                    current_segment["speaker"] = speaker
                    last_speaker = speaker

            if current_segment:
                labelled_segments.append(current_segment)
            continue

        turns = _overlapping_turns(start, end, speaker_turns)
        text = str(segment.get("text", "")).strip()
        if len(turns) > 1 and text:
            pieces = _split_text_by_turns(text, turns)
            for turn, piece in zip(turns, pieces):
                if not piece:
                    continue
                labelled_segment = dict(segment)
                labelled_segment["text"] = piece
                labelled_segment["start"] = float(turn["start"])
                labelled_segment["end"] = float(turn["end"])
                labelled_segment["speaker"] = str(turn["speaker"])
                labelled_segment["words"] = []
                labelled_segments.append(labelled_segment)
                last_speaker = str(turn["speaker"])
            continue

        speaker = _best_speaker(start, end, speaker_turns, last_speaker)

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
