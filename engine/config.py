"""Centralized configuration for the P.E.K.K.A Jarvis-style offline STT backend."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
DEFAULT_CACHE_DIR = ENGINE_DIR / ".cache" / "parakeet"
DEFAULT_WHISPER_CACHE_DIR = ENGINE_DIR / ".cache" / "whisper"

DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
)

DEFAULT_MODEL = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
DEFAULT_WHISPER_MODEL = "base"


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
class ParakeetConfig:
    model_name: str
    cache_dir: Path
    local_files_only: bool


@dataclass(frozen=True)
class WhisperConfig:
    model_name: str
    cache_dir: Path
    device: str
    compute_type: str
    language: str | None
    task: str
    vad_filter: bool
    local_files_only: bool


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    max_upload_bytes: int
    cors_origins: tuple[str, ...]
    parakeet: ParakeetConfig
    whisper: WhisperConfig


def load_config() -> ServerConfig:
    cache_dir = Path(
        os.getenv("PEKKA_MODEL_CACHE_DIR") or os.getenv("NOVA_MODEL_CACHE_DIR") or str(DEFAULT_CACHE_DIR)
    ).expanduser().resolve()
    whisper_cache_dir = Path(
        os.getenv("PEKKA_WHISPER_CACHE_DIR", str(DEFAULT_WHISPER_CACHE_DIR))
    ).expanduser().resolve()
    max_upload_mb = int(os.getenv("PEKKA_MAX_UPLOAD_MB") or os.getenv("NOVA_MAX_UPLOAD_MB") or "25")

    model_name = (
        os.getenv("PEKKA_PARAKEET_MODEL")
        or os.getenv("PEKKA_PARAKEET_MODEL_DIR")
        or os.getenv("PEKKA_ASR_MODEL")
        or DEFAULT_MODEL
    ).strip() or DEFAULT_MODEL

    parakeet_cfg = ParakeetConfig(
        model_name=model_name,
        cache_dir=cache_dir,
        local_files_only=_parse_bool(os.getenv("PEKKA_PARAKEET_OFFLINE_ONLY"), False),
    )

    whisper_lang = os.getenv("PEKKA_WHISPER_LANGUAGE", "").strip() or None
    whisper_cfg = WhisperConfig(
        model_name=os.getenv("PEKKA_WHISPER_MODEL", DEFAULT_WHISPER_MODEL).strip() or DEFAULT_WHISPER_MODEL,
        cache_dir=whisper_cache_dir,
        device=os.getenv("PEKKA_WHISPER_DEVICE", "cpu").strip() or "cpu",
        compute_type=os.getenv("PEKKA_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8",
        language=whisper_lang,
        task=os.getenv("PEKKA_WHISPER_TASK", "transcribe").strip() or "transcribe",
        vad_filter=_parse_bool(os.getenv("PEKKA_WHISPER_VAD"), True),
        local_files_only=_parse_bool(os.getenv("PEKKA_WHISPER_OFFLINE_ONLY"), True),
    )

    return ServerConfig(
        host=(os.getenv("PEKKA_ENGINE_HOST") or os.getenv("NOVA_ENGINE_HOST") or "127.0.0.1").strip() or "127.0.0.1",
        port=int(os.getenv("PEKKA_ENGINE_PORT") or os.getenv("NOVA_ENGINE_PORT") or "8000"),
        max_upload_bytes=max(1, max_upload_mb) * 1024 * 1024,
        cors_origins=_parse_origins(os.getenv("PEKKA_CORS_ORIGINS") or os.getenv("NOVA_CORS_ORIGINS")),
        parakeet=parakeet_cfg,
        whisper=whisper_cfg,
    )
