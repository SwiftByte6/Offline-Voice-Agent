"""HTTP endpoints for NOVA speech engine health and audio transcription."""

import asyncio
import os
from pathlib import Path
import tempfile

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from engine.speech.whisper_service import (
    InvalidAudioError,
    ModelLoadingError,
    ModelUnavailableError,
    TranscriptionError,
    WhisperService,
)

ALLOWED_AUDIO_EXTENSIONS = {".webm", ".wav", ".ogg", ".opus", ".mp3", ".m4a", ".mp4", ".flac"}
ALLOWED_CONTENT_TYPE_PREFIXES = ("audio/", "video/webm")
UPLOAD_CHUNK_SIZE = 64 * 1024

router = APIRouter()


def _resolve_suffix(file: UploadFile) -> str:
    if file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext in ALLOWED_AUDIO_EXTENSIONS:
            return ext

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    mime_to_ext = {
        "audio/webm": ".webm",
        "video/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/aac": ".m4a",
        "audio/flac": ".flac",
    }
    return mime_to_ext.get(content_type, ".webm")


def _validate_upload_headers(file: UploadFile) -> None:
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    ext = Path(file.filename).suffix.lower() if file.filename else ""

    has_valid_mime = any(
        content_type.startswith(prefix) for prefix in ALLOWED_CONTENT_TYPE_PREFIXES
    )
    has_valid_ext = ext in ALLOWED_AUDIO_EXTENSIONS

    if content_type and not has_valid_mime and not has_valid_ext:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format '{content_type}'.",
        )


async def _write_temp_audio(file: UploadFile, max_bytes: int) -> Path:
    suffix = _resolve_suffix(file)
    fd, raw_path = tempfile.mkstemp(prefix="nova_audio_", suffix=suffix)
    temp_path = Path(raw_path)
    total_bytes = 0

    try:
        with os.fdopen(fd, "wb") as out_stream:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Audio upload exceeds maximum allowed size of {max_bytes // (1024 * 1024)} MB.",
                    )
                out_stream.write(chunk)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    if total_bytes == 0:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")

    return temp_path


@router.get("/health")
async def get_health(request: Request) -> dict:
    whisper_service: WhisperService = request.app.state.whisper_service
    return {
        "status": "ok",
        "model_status": whisper_service.status,
        "model": whisper_service.config.model_name,
        "ready": whisper_service.ready,
        "error": whisper_service.error,
    }


@router.post("/api/transcribe")
async def transcribe_audio(request: Request, file: UploadFile = File(...)) -> dict:
    whisper_service: WhisperService = request.app.state.whisper_service
    transcription_lock: asyncio.Lock = request.app.state.transcription_lock
    max_upload_bytes: int = request.app.state.config.max_upload_bytes

    if whisper_service.status == "loading":
        raise HTTPException(
            status_code=503,
            detail="Whisper model is still loading. Please try again shortly.",
        )
    if not whisper_service.ready:
        raise HTTPException(
            status_code=503,
            detail=whisper_service.error or "Whisper model is unavailable.",
        )

    if transcription_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Another transcription is already in progress.",
        )

    _validate_upload_headers(file)

    temp_path: Path | None = None
    try:
        async with transcription_lock:
            temp_path = await _write_temp_audio(file, max_upload_bytes)
            result = await asyncio.to_thread(whisper_service.transcribe_file, temp_path)

        return {
            "success": True,
            "text": result.text,
            "language": result.language,
            "duration": result.duration,
        }
    except ModelLoadingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ModelUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InvalidAudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TranscriptionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        await file.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
