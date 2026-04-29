"""Formatting helpers for transcription copy, download, and LLM input."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.models import TranscriptionJob
from app.services.speaker_diarization import build_speaker_blocks


def _segments(job: TranscriptionJob) -> list[dict[str, Any]]:
    if not isinstance(job.result_segments, list):
        return []
    return [segment for segment in job.result_segments if isinstance(segment, dict)]


def _chunks(job: TranscriptionJob) -> list[Any]:
    try:
        chunks = list(getattr(job, "chunks", []) or [])
    except Exception:
        return []
    return sorted(chunks, key=lambda chunk: getattr(chunk, "chunk_index", 0))


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def safe_download_stem(job: TranscriptionJob, prefix: str = "transcription") -> str:
    """Return an ASCII-safe filename stem for attachment downloads."""
    source_name = job.audio_file.original_filename if job.audio_file else prefix
    stem = Path(source_name).stem or prefix
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    if not stem:
        stem = prefix
    return f"{stem}-{str(job.id)[:8]}"


def format_timecode(seconds: object, *, include_millis: bool = False) -> str:
    try:
        total_millis = int(round(max(0.0, float(seconds or 0.0)) * 1000))
    except (TypeError, ValueError):
        total_millis = 0

    total_seconds, millis = divmod(total_millis, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if include_millis:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def build_speaker_text(job: TranscriptionJob, *, fallback_to_result: bool = True) -> str:
    """Build a speaker-labelled plain text transcript when diarization exists."""
    blocks = build_speaker_blocks(_segments(job))
    if not blocks:
        return (job.result_text or "") if fallback_to_result else ""

    lines: list[str] = []
    for block in blocks:
        start = format_timecode(block.get("start"))
        end = format_timecode(block.get("end"))
        speaker = str(block.get("speaker", "SPEAKER"))
        text = str(block.get("text", "")).strip()
        if not text:
            continue
        lines.append(f"[{start}-{end}] {speaker}: {text}")
    return "\n\n".join(lines)


def build_summary_input_text(job: TranscriptionJob) -> str:
    """Return the transcript text that should be sent to the LLM."""
    refined_text = build_refined_transcript_text(job)
    if refined_text.strip():
        return refined_text

    speaker_text = build_speaker_text(job, fallback_to_result=False)
    if speaker_text.strip():
        return speaker_text
    return job.result_text or ""


def build_refined_transcript_text(job: TranscriptionJob, *, include_timecodes: bool = False) -> str:
    """Return chunk-refined transcript text when available."""
    chunk_lines: list[str] = []
    for chunk in _chunks(job):
        text = (getattr(chunk, "refined_text", None) or getattr(chunk, "raw_text", "") or "").strip()
        if not text:
            continue
        if include_timecodes:
            start = format_timecode(getattr(chunk, "start_seconds", 0.0))
            end = format_timecode(getattr(chunk, "end_seconds", 0.0))
            chunk_lines.append(f"[{start}-{end}] {text}")
        else:
            chunk_lines.append(text)
    return "\n\n".join(chunk_lines)


def build_summary_prompt_context(job: TranscriptionJob) -> dict[str, object]:
    audio_file = job.audio_file
    duration_seconds = audio_file.duration_seconds if audio_file else None
    raw_text = job.result_text or ""
    refined_text = build_refined_transcript_text(job)
    speaker_text = build_speaker_text(job, fallback_to_result=False)
    return {
        "text": build_summary_input_text(job),
        "raw_text": raw_text,
        "refined_text": refined_text,
        "speaker_text": speaker_text,
        "filename": audio_file.original_filename if audio_file else "",
        "engine": job.engine.value if job.engine else "",
        "model_size": job.model_size or "",
        "language": job.language or "",
        "duration": audio_file.duration_display if audio_file else "",
        "duration_seconds": duration_seconds if duration_seconds is not None else "",
        "speaker_diarization": "enabled" if job.enable_speaker_diarization else "disabled",
    }


def build_webvtt(job: TranscriptionJob) -> str:
    """Build a WebVTT subtitle file from timestamped transcription segments."""
    cues: list[str] = ["WEBVTT", ""]
    segments = _segments(job)

    if not segments and job.result_text:
        segments = [{"start": 0.0, "end": 1.0, "text": job.result_text}]

    for segment in segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue

        start_value = segment.get("start", 0.0)
        end_value = segment.get("end", start_value)
        try:
            start = float(start_value or 0.0)
            end = float(end_value or start)
        except (TypeError, ValueError):
            start = 0.0
            end = 0.0
        if end <= start:
            end = start + 1.0

        speaker = segment.get("speaker")
        cue_text = re.sub(r"\s+", " ", text).replace("-->", "->")
        if speaker:
            cue_text = f"{speaker}: {cue_text}"

        cues.append(
            f"{format_timecode(start, include_millis=True)} --> "
            f"{format_timecode(end, include_millis=True)}"
        )
        cues.append(cue_text)
        cues.append("")

    return "\n".join(cues)


def build_result_json(job: TranscriptionJob) -> str:
    audio_file = job.audio_file
    payload = {
        "id": str(job.id),
        "status": job.status.value,
        "engine": job.engine.value,
        "model_size": job.model_size,
        "language": job.language,
        "enable_speaker_diarization": job.enable_speaker_diarization,
        "progress_percent": job.progress_percent,
        "error_message": job.error_message,
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "completed_at": _iso(job.completed_at),
        "audio_file": None,
        "result_text": job.result_text,
        "result_segments": _segments(job),
        "speaker_blocks": build_speaker_blocks(_segments(job)),
    }
    if audio_file:
        payload["audio_file"] = {
            "id": str(audio_file.id),
            "source": audio_file.source.value,
            "original_filename": audio_file.original_filename,
            "stored_filename": audio_file.stored_filename,
            "file_size": audio_file.file_size,
            "mime_type": audio_file.mime_type,
            "duration_seconds": audio_file.duration_seconds,
            "created_at": _iso(audio_file.created_at),
            "expires_at": _iso(audio_file.expires_at),
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)
