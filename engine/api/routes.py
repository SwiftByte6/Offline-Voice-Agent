"""HTTP endpoints for NOVA speech engine health and audio transcription."""

import asyncio
import os
from pathlib import Path
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

import cv2
import numpy as np

from engine.speech.stt_service import (
    InvalidAudioError,
    ModelLoadingError,
    ModelUnavailableError,
    OfflineSTTService,
    TranscriptionError,
)
from engine.vision.service import (
    capture_screen,
    execute_action,
    run_ocr,
    screenshot_base64,
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
    speech_service: OfflineSTTService = request.app.state.speech_service
    return {
        "status": "ok",
        "model_status": speech_service.status,
        "model": speech_service.model_name,
        "ready": speech_service.ready,
        "parakeet_ready": speech_service.parakeet.ready,
        "whisper_ready": speech_service.whisper.ready,
        "error": speech_service.error,
    }


@router.post("/api/transcribe")
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),
    language: str | None = Form(None),
    strip_name: bool = Form(False),
    engine: str | None = Form(None),
) -> dict:
    speech_service: OfflineSTTService = request.app.state.speech_service
    transcription_lock: asyncio.Lock = request.app.state.transcription_lock
    max_upload_bytes: int = request.app.state.config.max_upload_bytes

    if speech_service.status == "loading":
        raise HTTPException(
            status_code=503,
            detail="Speech model is still loading. Please try again shortly.",
        )
    if not speech_service.ready:
        raise HTTPException(
            status_code=503,
            detail=speech_service.error or "Speech model is unavailable.",
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
            result = await asyncio.to_thread(
                speech_service.transcribe_file,
                temp_path,
                language=language,
                strip_name=strip_name,
                preferred_engine=engine,
            )

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


@router.get("/api/screen")
async def get_screen() -> dict:
    """Capture the primary monitor and return it as base64 PNG."""
    image_b64, width, height = screenshot_base64()
    return {"image": image_b64, "width": width, "height": height}


@router.post("/api/ocr")
async def ocr_screen(file: UploadFile | None = File(None)) -> dict:
    """Run OCR on an uploaded image or (by default) the current screen."""
    if file is not None:
        data = await file.read()
        await file.close()
        arr = np.frombuffer(data, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            raise HTTPException(status_code=400, detail="Could not decode uploaded image.")
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    else:
        from engine.vision.service import capture_screen_array

        image, _, _ = capture_screen_array()

    items = run_ocr(image)
    return {"items": items, "count": len(items)}


@router.post("/api/act")
async def act(request: Request) -> dict:
    """Execute a desktop action (click/type/hotkey/scroll/move)."""
    try:
        action = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc

    if not isinstance(action, dict):
        raise HTTPException(status_code=400, detail="Action must be a JSON object.")

    # Attach screen dimensions for coordinate scaling when missing.
    if "src_w" not in action or "src_h" not in action:
        try:
            from engine.vision.service import capture_screen_array

            _, w, h = capture_screen_array()
            action.setdefault("src_w", w)
            action.setdefault("src_h", h)
        except Exception:  # noqa: BLE001
            pass

    return execute_action(action)


@router.get("/api/voice/status")
async def voice_status(request: Request) -> dict:
    pipeline = request.app.state.pekka_pipeline
    llm_info: dict[str, object] = {"configured": pipeline.llm is not None, "model": getattr(pipeline.llm, "model", None)}
    if pipeline.llm is not None:
        try:
            models = await pipeline.llm.list_models()
            llm_info["reachable"] = True
            llm_info["available_models"] = models
        except Exception as exc:  # noqa: BLE001
            llm_info["reachable"] = False
            llm_info["error"] = str(exc)
    return {
        "llm": llm_info,
        "tts": {"available": pipeline.tts.available, "exe": pipeline.tts.exe or None, "model": pipeline.tts.model or None},
        "pending_approval": pipeline.pending_summary(),
        "recent_turns": len(pipeline.memory.recent_turns()),
    }


@router.post("/api/voice/speak")
async def voice_speak(request: Request) -> dict:
    """Synthesize speech via Piper TTS (returns base64 WAV and optionally plays locally)."""
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc
    if not isinstance(body, dict) or not body.get("text"):
        raise HTTPException(status_code=400, detail="Missing 'text'.")
    pipeline = request.app.state.pekka_pipeline
    res = await pipeline.tts.speak(str(body["text"]), play_local=bool(body.get("play_local", False)))
    return res.to_dict()


@router.post("/api/voice/stop_speaking")
async def voice_stop_speaking(request: Request) -> dict:
    pipeline = request.app.state.pekka_pipeline
    pipeline.tts.stop()
    return {"stopped": True}


@router.post("/api/voice/command")
async def voice_command(request: Request) -> dict:
    """Run a text transcript through the offline LLM + memory + permission pipeline."""
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc
    if not isinstance(body, dict) or not body.get("transcript"):
        raise HTTPException(status_code=400, detail="Missing 'transcript'.")
    pipeline = request.app.state.pekka_pipeline
    result = await pipeline.run(
        transcript=str(body["transcript"]),
        speak=bool(body.get("speak", False)),
        play_local=bool(body.get("play_local", False)),
        approval=bool(body.get("approval", False)),
        require_wake_word=bool(body.get("require_wake_word", False)),
        wake_name=str(body.get("wake_name") or "P.E.K.K.A"),
    )
    return result.to_dict()


@router.post("/api/voice/agent")
async def voice_agent(
    request: Request,
    file: UploadFile = File(...),
    speak: bool = Form(False),
    play_local: bool = Form(False),
    approval: bool = Form(False),
    require_wake_word: bool = Form(False),
    wake_name: str = Form("P.E.K.K.A"),
    language: str | None = Form(None),
) -> dict:
    """Audio upload -> Offline STT -> Local LLM / offline fallback -> Permission -> Tool."""
    speech_service: OfflineSTTService = request.app.state.speech_service
    transcription_lock: asyncio.Lock = request.app.state.transcription_lock
    max_upload_bytes: int = request.app.state.config.max_upload_bytes

    if speech_service.status == "loading":
        raise HTTPException(status_code=503, detail="Speech model is still loading.")
    if not speech_service.ready:
        raise HTTPException(status_code=503, detail=speech_service.error or "Speech model is unavailable.")
    if transcription_lock.locked():
        raise HTTPException(status_code=409, detail="Another transcription is already in progress.")

    _validate_upload_headers(file)
    temp_path: Path | None = None
    try:
        async with transcription_lock:
            temp_path = await _write_temp_audio(file, max_upload_bytes)
            pipeline = request.app.state.pekka_pipeline
            result = await pipeline.run(
                audio_path=temp_path,
                speak=speak,
                play_local=play_local,
                approval=approval,
                require_wake_word=require_wake_word,
                wake_name=wake_name,
                language=language,
            )
        return result.to_dict()
    finally:
        await file.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
