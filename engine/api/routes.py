"""HTTP endpoints for NOVA speech engine health and audio transcription."""

import asyncio
import logging
import os
from pathlib import Path
import tempfile

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

import cv2
import numpy as np

from engine.speech.qwen_asr_service import (
    InvalidAudioError,
    ModelLoadingError,
    ModelUnavailableError,
    TranscriptionError,
    QwenASRService,
)
from engine.agent.desktop_agent import DesktopAgent, PlanValidationError
from engine.llm.lfm_service import LFMService, LLMLoadingError, LLMUnavailableError
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
logger = logging.getLogger("nova.api")


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
    qwen_asr_service: QwenASRService = request.app.state.qwen_asr_service
    lfm_service: LFMService = request.app.state.lfm_service
    return {
        "status": "ok",
        "agent_version": "desktop-agent-v6",
        "model_status": qwen_asr_service.status,
        "model": qwen_asr_service.config.model_name,
        "ready": qwen_asr_service.ready and lfm_service.ready,
        "error": qwen_asr_service.error or lfm_service.error,
        "llm_status": lfm_service.status,
        "llm_model": f"{lfm_service.config.model_repo}:{lfm_service.config.model_file}",
        "llm_ready": lfm_service.ready,
        "llm_error": lfm_service.error,
    }


@router.post("/api/transcribe")
async def transcribe_audio(request: Request, file: UploadFile = File(...)) -> dict:
    qwen_asr_service: QwenASRService = request.app.state.qwen_asr_service
    transcription_lock: asyncio.Lock = request.app.state.transcription_lock
    agent_lock: asyncio.Lock = request.app.state.agent_lock
    desktop_agent: DesktopAgent = request.app.state.desktop_agent
    max_upload_bytes: int = request.app.state.config.max_upload_bytes

    if qwen_asr_service.status == "loading":
        raise HTTPException(
            status_code=503,
            detail="Qwen3-ASR model is still loading. Please try again shortly.",
        )
    if not qwen_asr_service.ready:
        raise HTTPException(
            status_code=503,
            detail=qwen_asr_service.error or "Qwen3-ASR model is unavailable.",
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
            result = await asyncio.to_thread(qwen_asr_service.transcribe_file, temp_path)

        logger.info("Transcription received by agent: %s", result.text)

        agent_result = None
        async with agent_lock:
            agent_result = await asyncio.to_thread(desktop_agent.run, result.text)

        return {
            "success": True,
            "text": result.text,
            "language": result.language,
            "duration": result.duration,
            "agent": agent_result,
        }
    except ModelLoadingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ModelUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InvalidAudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TranscriptionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except LLMLoadingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PlanValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail="Could not capture or inspect the desktop. Start the engine in your interactive Windows session.",
        ) from exc
    finally:
        await file.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@router.post("/api/agent/run")
async def run_desktop_agent(request: Request) -> dict:
    """Plan and optionally execute actions for a typed desktop instruction."""
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc

    instruction = str(payload.get("instruction", "")).strip() if isinstance(payload, dict) else ""
    if not instruction:
        raise HTTPException(status_code=400, detail="Instruction is required.")
    if len(instruction) > 2_000:
        raise HTTPException(status_code=400, detail="Instruction exceeds 2,000 characters.")

    execute = bool(payload.get("execute", True))
    desktop_agent: DesktopAgent = request.app.state.desktop_agent
    agent_lock: asyncio.Lock = request.app.state.agent_lock
    try:
        async with agent_lock:
            return await asyncio.to_thread(desktop_agent.run, instruction, execute)
    except LLMLoadingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PlanValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail="Could not capture or inspect the desktop. Start the engine in your interactive Windows session.",
        ) from exc


@router.post("/api/agent/confirm")
async def confirm_desktop_agent_action(request: Request) -> dict:
    """Approve or reject an action paused by the desktop agent."""
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Action confirmation must be a JSON object.")

    confirmation_id = str(payload.get("confirmation_id", "")).strip()
    if not confirmation_id:
        raise HTTPException(status_code=400, detail="confirmation_id is required.")
    approved = bool(payload.get("approved", False))
    desktop_agent: DesktopAgent = request.app.state.desktop_agent
    agent_lock: asyncio.Lock = request.app.state.agent_lock
    try:
        async with agent_lock:
            return await asyncio.to_thread(desktop_agent.confirm, confirmation_id, approved)
    except PlanValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
