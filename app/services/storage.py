import shutil
import uuid
from datetime import datetime
from pathlib import Path

import aiofiles

from app.config import get_settings

settings = get_settings()

# Allowed audio MIME types
ALLOWED_AUDIO_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/wave": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
}

UPLOAD_STREAM_CHUNK_SIZE = 4 * 1024 * 1024  # 4MB


def get_upload_dir() -> Path:
    """Get the upload directory, creating it if necessary."""
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def get_chunks_dir() -> Path:
    """Get the chunks directory, creating it if necessary."""
    chunks_dir = get_upload_dir() / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    return chunks_dir


def get_date_based_dir(base_dir: Path) -> Path:
    """Get a date-based subdirectory (YYYY/MM/DD format)."""
    today = datetime.now()
    date_dir = base_dir / str(today.year) / f"{today.month:02d}" / f"{today.day:02d}"
    date_dir.mkdir(parents=True, exist_ok=True)
    return date_dir


def generate_stored_filename(original_filename: str, extension: str | None = None) -> str:
    """Generate a unique stored filename."""
    if extension is None:
        extension = Path(original_filename).suffix
    unique_id = uuid.uuid4().hex[:12]
    return f"{unique_id}{extension}"


def validate_audio_mime_type(mime_type: str | None) -> bool:
    """Check if the MIME type is an allowed audio type."""
    if mime_type is None:
        return False
    return mime_type.lower() in ALLOWED_AUDIO_TYPES


def get_extension_for_mime_type(mime_type: str) -> str:
    """Get the file extension for a MIME type."""
    return ALLOWED_AUDIO_TYPES.get(mime_type.lower(), ".bin")


async def save_upload_file(
    file_content: bytes,
    original_filename: str,
    mime_type: str | None = None,
) -> tuple[str, str]:
    """
    Save an uploaded file to the storage directory.

    Returns:
        Tuple of (stored_filename, file_path)
    """
    upload_dir = get_date_based_dir(get_upload_dir())

    # Determine extension
    if mime_type and mime_type in ALLOWED_AUDIO_TYPES:
        extension = ALLOWED_AUDIO_TYPES[mime_type]
    else:
        extension = Path(original_filename).suffix or ".bin"

    stored_filename = generate_stored_filename(original_filename, extension)
    file_path = upload_dir / stored_filename

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(file_content)

    return stored_filename, str(file_path)


async def save_upload_stream(
    upload_file,
    original_filename: str,
    max_size: int,
    mime_type: str | None = None,
    chunk_size: int = UPLOAD_STREAM_CHUNK_SIZE,
) -> tuple[str, str, int]:
    """
    Stream an uploaded file to disk while enforcing a maximum size.

    Returns:
        Tuple of (stored_filename, file_path, file_size)
    """
    upload_dir = get_date_based_dir(get_upload_dir())

    if mime_type and mime_type in ALLOWED_AUDIO_TYPES:
        extension = ALLOWED_AUDIO_TYPES[mime_type]
    else:
        extension = Path(original_filename).suffix or ".bin"

    stored_filename = generate_stored_filename(original_filename, extension)
    file_path = upload_dir / stored_filename
    total_size = 0

    try:
        async with aiofiles.open(file_path, "wb") as f:
            while True:
                chunk = await upload_file.read(chunk_size)
                if not chunk:
                    break

                total_size += len(chunk)
                if total_size > max_size:
                    raise ValueError("File too large")

                await f.write(chunk)
    except Exception:
        file_path.unlink(missing_ok=True)
        raise

    return stored_filename, str(file_path), total_size


async def save_chunk_file(
    session_id: uuid.UUID,
    chunk_index: int,
    file_content: bytes,
) -> tuple[str, int]:
    """
    Save a recording chunk to the chunks directory.

    Returns:
        Tuple of (file_path, file_size)
    """
    chunks_dir = get_chunks_dir() / str(session_id)
    chunks_dir.mkdir(parents=True, exist_ok=True)

    chunk_filename = f"chunk_{chunk_index:05d}.webm"
    file_path = chunks_dir / chunk_filename

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(file_content)

    return str(file_path), len(file_content)


def get_chunk_files(session_id: uuid.UUID) -> list[Path]:
    """Get all chunk files for a recording session, sorted by index."""
    chunks_dir = get_chunks_dir() / str(session_id)
    if not chunks_dir.exists():
        return []

    chunk_files = sorted(chunks_dir.glob("chunk_*.webm"))
    return chunk_files


def delete_file(file_path: str) -> bool:
    """Delete a file from storage."""
    path = Path(file_path)
    if path.exists():
        path.unlink()
        return True
    return False


def delete_session_chunks(session_id: uuid.UUID) -> bool:
    """Delete all chunks for a recording session."""
    chunks_dir = get_chunks_dir() / str(session_id)
    if chunks_dir.exists():
        shutil.rmtree(chunks_dir)
        return True
    return False


def get_file_size(file_path: str) -> int:
    """Get the size of a file in bytes."""
    path = Path(file_path)
    if path.exists():
        return path.stat().st_size
    return 0


async def save_recording_chunk(
    audio_bytes: bytes,
    session_id: str,
    chunk_index: int,
) -> tuple[str, str]:
    """
    Save a recording chunk to the chunks directory.

    Returns:
        Tuple of (chunk_filename, file_path)
    """
    chunks_dir = get_chunks_dir() / session_id
    chunks_dir.mkdir(parents=True, exist_ok=True)

    chunk_filename = f"chunk_{chunk_index:05d}.webm"
    file_path = chunks_dir / chunk_filename

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(audio_bytes)

    return chunk_filename, str(file_path)


async def merge_recording_chunks(
    chunk_files: list[str],
    session_id: str,
) -> tuple[str, str, int]:
    """
    Merge recording chunks into a single audio file using ffmpeg.

    Each chunk from the browser already contains a webm initialization segment,
    so we use ffmpeg's concat demuxer to properly merge them.

    Returns:
        Tuple of (stored_filename, file_path, file_size)
    """
    import asyncio
    import tempfile

    upload_dir = get_date_based_dir(get_upload_dir())
    stored_filename = f"recording_{session_id[:12]}.webm"
    output_path = upload_dir / stored_filename

    sorted_chunks = sorted(f for f in chunk_files if Path(f).exists())

    if not sorted_chunks:
        output_path.touch()
        return stored_filename, str(output_path), 0

    if len(sorted_chunks) == 1:
        # Single chunk: just copy
        shutil.copy2(sorted_chunks[0], output_path)
        total_size = output_path.stat().st_size
        return stored_filename, str(output_path), total_size

    # Write ffmpeg concat list file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        concat_list_path = f.name
        for chunk in sorted_chunks:
            # ffmpeg concat format requires escaped paths
            escaped = chunk.replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            str(output_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            # Fallback: raw concatenation
            BUFFER_SIZE = 64 * 1024
            async with aiofiles.open(output_path, "wb") as outfile:
                for chunk_file in sorted_chunks:
                    async with aiofiles.open(chunk_file, "rb") as infile:
                        while True:
                            buf = await infile.read(BUFFER_SIZE)
                            if not buf:
                                break
                            await outfile.write(buf)
    finally:
        Path(concat_list_path).unlink(missing_ok=True)

    total_size = output_path.stat().st_size if output_path.exists() else 0
    return stored_filename, str(output_path), total_size


async def cleanup_recording_chunks(chunk_files: list[str]) -> None:
    """Clean up recording chunk files after merging."""
    for chunk_file in chunk_files:
        path = Path(chunk_file)
        if path.exists():
            path.unlink()

    # Try to remove the session directory if empty
    if chunk_files:
        session_dir = Path(chunk_files[0]).parent
        try:
            session_dir.rmdir()
        except OSError:
            pass  # Directory not empty or doesn't exist
