"""Centralized configuration for the NOVA Qwen3-ASR backend."""

from dataclasses import dataclass
import os
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = ENGINE_DIR.parent
DEFAULT_CACHE_DIR = ENGINE_DIR / ".cache" / "qwen-asr"


def _load_dotenv() -> None:
    """Load key=value pairs from .env files without overriding existing env vars."""
    for env_path in (REPO_ROOT / ".env", ENGINE_DIR / ".env"):
        if not env_path.is_file():
            continue
        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            continue

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
class QwenASRConfig:
    model_name: str
    device: str
    dtype: str
    language: str | None
    cache_dir: Path
    local_files_only: bool
    max_new_tokens: int


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str | None
    model: str
    timeout_seconds: float
    max_steps: int


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    max_upload_bytes: int
    cors_origins: tuple[str, ...]
    qwen_asr: QwenASRConfig
    gemini: GeminiConfig


def load_config() -> ServerConfig:
    _load_dotenv()

    raw_language = os.getenv("NOVA_QWEN_ASR_LANGUAGE", "").strip()
    language = raw_language if raw_language else None

    cache_dir = Path(
        os.getenv("NOVA_MODEL_CACHE_DIR", str(DEFAULT_CACHE_DIR))
    ).expanduser().resolve()

    max_upload_mb = int(os.getenv("NOVA_MAX_UPLOAD_MB", "25"))

    qwen_asr_cfg = QwenASRConfig(
        model_name=(
            os.getenv("NOVA_QWEN_ASR_MODEL", "Qwen/Qwen3-ASR-0.6B").strip()
            or "Qwen/Qwen3-ASR-0.6B"
        ),
        device=os.getenv("NOVA_QWEN_ASR_DEVICE", "cpu").strip() or "cpu",
        dtype=os.getenv("NOVA_QWEN_ASR_DTYPE", "float32").strip() or "float32",
        language=language,
        cache_dir=cache_dir,
        local_files_only=_parse_bool(os.getenv("NOVA_QWEN_ASR_OFFLINE_ONLY"), False),
        max_new_tokens=max(1, int(os.getenv("NOVA_QWEN_ASR_MAX_NEW_TOKENS", "512"))),
    )

    gemini_key = (
        os.getenv("NOVA_GEMINI_API_KEY", "").strip()
        or os.getenv("GEMINI_API_KEY", "").strip()
        or None
    )
    gemini_cfg = GeminiConfig(
        api_key=gemini_key,
        model=os.getenv("NOVA_GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash",
        timeout_seconds=max(5.0, float(os.getenv("NOVA_GEMINI_TIMEOUT", "25"))),
        max_steps=max(1, min(10, int(os.getenv("NOVA_GEMINI_MAX_STEPS", "6")))),
    )

    return ServerConfig(
        host=os.getenv("NOVA_ENGINE_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=int(os.getenv("NOVA_ENGINE_PORT", "8000")),
        max_upload_bytes=max(1, max_upload_mb) * 1024 * 1024,
        cors_origins=_parse_origins(os.getenv("NOVA_CORS_ORIGINS")),
        qwen_asr=qwen_asr_cfg,
        gemini=gemini_cfg,
    )
