"""Centralized configuration for the NOVA Faster-Whisper backend."""

from dataclasses import dataclass
import os
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
DEFAULT_CACHE_DIR = ENGINE_DIR / ".cache" / "whisper"

DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
)


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_origins(raw: str | None) -> tuple[str, ...]:
    if not raw or not raw.strip():
        return DEFAULT_CORS_ORIGINS
    origins = tuple(item.strip() for item in raw.split(",") if item.strip())
    return origins or DEFAULT_CORS_ORIGINS


@dataclass(frozen=True)
class WhisperConfig:
    model_name: str
    device: str
    compute_type: str
    language: str | None
    task: str
    vad_filter: bool
    cache_dir: Path
    local_files_only: bool


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    max_upload_bytes: int
    cors_origins: tuple[str, ...]
    whisper: WhisperConfig


def load_config() -> ServerConfig:
    raw_language = os.getenv("NOVA_WHISPER_LANGUAGE", "").strip()
    language = raw_language if raw_language else None

    cache_dir = Path(
        os.getenv("NOVA_MODEL_CACHE_DIR", str(DEFAULT_CACHE_DIR))
    ).expanduser().resolve()

    max_upload_mb = int(os.getenv("NOVA_MAX_UPLOAD_MB", "25"))

    whisper_cfg = WhisperConfig(
        model_name=os.getenv("NOVA_WHISPER_MODEL", "base").strip() or "base",
        device=os.getenv("NOVA_WHISPER_DEVICE", "cpu").strip() or "cpu",
        compute_type=os.getenv("NOVA_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8",
        language=language,
        task=os.getenv("NOVA_WHISPER_TASK", "transcribe").strip() or "transcribe",
        vad_filter=_parse_bool(os.getenv("NOVA_WHISPER_VAD_FILTER"), True),
        cache_dir=cache_dir,
        local_files_only=_parse_bool(os.getenv("NOVA_WHISPER_OFFLINE_ONLY"), False),
    )

    return ServerConfig(
        host=os.getenv("NOVA_ENGINE_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=int(os.getenv("NOVA_ENGINE_PORT", "8000")),
        max_upload_bytes=max(1, max_upload_mb) * 1024 * 1024,
        cors_origins=_parse_origins(os.getenv("NOVA_CORS_ORIGINS")),
        whisper=whisper_cfg,
    )
