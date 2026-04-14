"""
WebSocket endpoint for browser recording and streaming transcription.
"""
import asyncio
import base64
import json
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_user_from_session_cookie
from app.models import AudioFile, AudioSource, RecordingChunk, RecordingSession, RecordingStatus
from app.models import TranscriptionEngine, TranscriptionJob
from app.models.user import User
from app.schemas.recording import WSChunkReceived, WSError, WSTranscriptionResult
from app.services import storage
from app.time_utils import utc_now

settings = get_settings()
router = APIRouter(tags=["recording"])

# Store active WebSocket connections
active_connections: dict[str, WebSocket] = {}
active_transcription_tasks: dict[str, set[asyncio.Task]] = {}


class ConnectionManager:
    """Manage WebSocket connections for recording sessions."""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[session_id] = websocket

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]

    async def send_message(self, session_id: str, message: dict):
        if session_id in self.active_connections:
            await self.active_connections[session_id].send_json(message)

    async def send_error(self, session_id: str, error_message: str):
        await self.send_message(session_id, WSError(message=error_message).model_dump())

    async def send_chunk_received(self, session_id: str, chunk_index: int, total_duration: float):
        await self.send_message(
            session_id,
            WSChunkReceived(chunk_index=chunk_index, total_duration=total_duration).model_dump()
        )

    async def send_transcription(
        self,
        session_id: str,
        text: str,
        is_partial: bool = False,
        segment_start: float | None = None,
        segment_end: float | None = None,
    ):
        await self.send_message(
            session_id,
            WSTranscriptionResult(
                text=text,
                is_partial=is_partial,
                segment_start=segment_start,
                segment_end=segment_end,
            ).model_dump()
        )


manager = ConnectionManager()


def track_transcription_task(session_id: str, task: asyncio.Task) -> None:
    tasks = active_transcription_tasks.setdefault(session_id, set())
    tasks.add(task)

    def _cleanup(done_task: asyncio.Task) -> None:
        session_tasks = active_transcription_tasks.get(session_id)
        if not session_tasks:
            return
        session_tasks.discard(done_task)
        if not session_tasks:
            active_transcription_tasks.pop(session_id, None)

    task.add_done_callback(_cleanup)


async def wait_for_transcription_tasks(session_id: str) -> None:
    tasks = list(active_transcription_tasks.get(session_id, set()))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def get_ws_user(websocket: WebSocket, db: Session) -> User | None:
    """Extract and validate user from WebSocket cookies."""
    session_cookie = websocket.cookies.get("session")
    if not session_cookie:
        return None

    return get_user_from_session_cookie(session_cookie, db)


@router.websocket("/ws/recording/{session_id}")
async def recording_websocket(
    websocket: WebSocket,
    session_id: str,
):
    """
    WebSocket endpoint for recording sessions.

    Messages from client:
    - {"type": "chunk", "chunk_index": int, "is_final": bool, "data": base64_string}
    - {"type": "pause"}
    - {"type": "resume"}

    Messages to client:
    - {"type": "chunk_received", "chunk_index": int, "total_duration": float}
    - {"type": "transcription", "text": str, "is_partial": bool}
    - {"type": "error", "message": str}
    """
    # Get database session
    from app.database import SessionLocal
    db = SessionLocal()

    try:
        # Authenticate user from cookie
        user = await get_ws_user(websocket, db)
        if not user:
            await websocket.close(code=4001, reason="Authentication required")
            return

        # Validate session_id format (UUID)
        try:
            session_uuid = uuid.UUID(session_id)
        except ValueError:
            await websocket.close(code=4002, reason="Invalid session ID")
            return

        # Accept connection
        await manager.connect(session_id, websocket)

        # Create or get recording session
        recording_session = await get_or_create_session(db, user, session_uuid)

        total_duration = 0.0
        chunk_files = []

        try:
            while True:
                # Receive message
                data = await websocket.receive_text()
                message = json.loads(data)

                msg_type = message.get("type")

                if msg_type == "chunk":
                    # Process audio chunk
                    chunk_index = message.get("chunk_index", 0)
                    is_final = message.get("is_final", False)
                    audio_data = message.get("data")
                    elapsed_ms = message.get("elapsed_ms")

                    if not audio_data:
                        await manager.send_error(session_id, "No audio data in chunk")
                        continue

                    # Decode base64 audio
                    try:
                        audio_bytes = base64.b64decode(audio_data)
                    except Exception as e:
                        await manager.send_error(session_id, f"Invalid audio data: {e}")
                        continue

                    # Save chunk
                    chunk_filename, chunk_path = await storage.save_recording_chunk(
                        audio_bytes,
                        session_id,
                        chunk_index,
                    )
                    chunk_files.append(chunk_path)

                    if isinstance(elapsed_ms, (int, float)) and elapsed_ms >= 0:
                        reported_total_duration = elapsed_ms / 1000.0
                    else:
                        reported_total_duration = total_duration

                    chunk_duration = max(0.0, reported_total_duration - total_duration)
                    total_duration = max(total_duration, reported_total_duration)

                    # Save chunk to database
                    chunk_record = RecordingChunk(
                        session_id=recording_session.id,
                        chunk_index=chunk_index,
                        file_path=chunk_path,
                        file_size=len(audio_bytes),
                        duration_seconds=chunk_duration,
                    )
                    db.add(chunk_record)

                    # Update session
                    recording_session.chunk_count = chunk_index + 1
                    recording_session.total_duration_seconds = total_duration
                    db.flush()  # chunk_record.id を取得するため
                    chunk_record_id = chunk_record.id
                    db.commit()

                    # チャンクをリアルタイムで文字起こし
                    task = asyncio.create_task(
                        transcribe_and_send(session_id, chunk_path, chunk_index, chunk_record_id)
                    )
                    track_transcription_task(session_id, task)

                    # Send confirmation
                    await manager.send_chunk_received(session_id, chunk_index, total_duration)

                    # If final chunk, finalize recording after all tracked tasks complete
                    if is_final:
                        await finalize_recording(
                            db, recording_session, user, chunk_files, total_duration
                        )
                        await manager.send_message(session_id, {
                            "type": "recording_complete",
                            "session_id": str(recording_session.id),
                        })

                elif msg_type == "pause":
                    recording_session.status = RecordingStatus.PAUSED
                    recording_session.paused_at = utc_now()
                    db.commit()

                elif msg_type == "resume":
                    recording_session.status = RecordingStatus.RECORDING
                    recording_session.paused_at = None
                    db.commit()

        except WebSocketDisconnect:
            # Handle unexpected disconnect
            if recording_session.status == RecordingStatus.RECORDING:
                recording_session.status = RecordingStatus.PAUSED
                recording_session.paused_at = utc_now()
                db.commit()

    except Exception as e:
        await manager.send_error(session_id, f"Server error: {str(e)}")
    finally:
        await wait_for_transcription_tasks(session_id)
        manager.disconnect(session_id)
        db.close()


async def get_or_create_session(
    db: Session,
    user: User,
    session_uuid: uuid.UUID,
) -> RecordingSession:
    """Get existing or create new recording session."""
    # Check for existing session
    stmt = select(RecordingSession).where(RecordingSession.id == session_uuid)
    existing = db.execute(stmt).scalar_one_or_none()

    if existing:
        if existing.user_id != user.id:
            raise ValueError("Session belongs to different user")
        return existing

    # Create new session
    session = RecordingSession(
        id=session_uuid,
        user_id=user.id,
        status=RecordingStatus.RECORDING,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return session


async def finalize_recording(
    db: Session,
    session: RecordingSession,
    user: User,
    chunk_files: list[str],
    total_duration: float,
):
    """Finalize recording: merge chunks and create transcription job."""
    await wait_for_transcription_tasks(str(session.id))

    # Merge chunks into single audio file
    merged_filename, merged_path, merged_size = await storage.merge_recording_chunks(
        chunk_files, str(session.id)
    )

    # Calculate expiration
    expires_at = utc_now() + timedelta(days=settings.audio_retention_days)

    # Create audio file record
    audio_file = AudioFile(
        user_id=user.id,
        source=AudioSource.RECORDING,
        original_filename=f"recording_{session.id}.webm",
        stored_filename=merged_filename,
        file_path=merged_path,
        file_size=merged_size,
        mime_type="audio/webm",
        duration_seconds=total_duration,
        expires_at=expires_at,
    )
    db.add(audio_file)
    db.flush()

    # Update session
    session.status = RecordingStatus.COMPLETED
    session.audio_file_id = audio_file.id
    session.completed_at = utc_now()
    session.total_duration_seconds = total_duration

    # Create transcription job
    job = TranscriptionJob(
        audio_file_id=audio_file.id,
        user_id=user.id,
        engine=TranscriptionEngine.FASTER_WHISPER,
        model_size="medium",
    )
    db.add(job)
    db.commit()

    # Clean up chunk files
    await storage.cleanup_recording_chunks(chunk_files)

    return job


async def transcribe_and_send(session_id: str, chunk_path: str, chunk_index: int, chunk_db_id):
    """チャンクファイルをWhisperで文字起こししてWebSocketで送信・DBに保存する"""
    import logging
    logger = logging.getLogger(__name__)
    try:
        from app.database import SessionLocal
        from app.services.transcription import transcribe_audio
        text, _ = await transcribe_audio(
            chunk_path,
            model_size=settings.whisper_model_size,
            language=settings.whisper_language,
            device=settings.whisper_device,
        )
        if text:
            # DBに保存
            db = SessionLocal()
            try:
                from app.models import RecordingChunk
                chunk = db.get(RecordingChunk, chunk_db_id)
                if chunk:
                    chunk.transcription_text = text
                    db.commit()
            finally:
                db.close()

            # WebSocketで送信（接続が残っていれば）
            await manager.send_message(session_id, {
                "type": "transcription",
                "text": text,
                "chunk_index": chunk_index,
                "is_partial": False,
            })
    except Exception as e:
        logger.warning("リアルタイム文字起こし失敗 (chunk %d): %s", chunk_index, e)
