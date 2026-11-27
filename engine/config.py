"""Centralized configuration for the NOVA Qwen3-ASR backend."""

from dataclasses import dataclass
import os
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
DEFAULT_CACHE_DIR = ENGINE_DIR / ".cache" / "qwen-asr"
DEFAULT_LLM_CACHE_DIR = ENGINE_DIR / ".cache" / "lfm3"

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
class LLMConfig:
    model_repo: str
    model_file: str
    cache_dir: Path
    context_tokens: int
    gpu_layers: int
    threads: int | None
    local_files_only: bool


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    max_upload_bytes: int
    cors_origins: tuple[str, ...]
    qwen_asr: QwenASRConfig
    llm: LLMConfig


def load_config() -> ServerConfig:
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

    llm_cache_dir = Path(
        os.getenv("NOVA_LLM_CACHE_DIR", str(DEFAULT_LLM_CACHE_DIR))
    ).expanduser().resolve()
    raw_threads = os.getenv("NOVA_LLM_THREADS", "").strip()
    llm_cfg = LLMConfig(
        model_repo=os.getenv("NOVA_LLM_MODEL_REPO", "LiquidAI/LFM3-1.7B-GGUF").strip()
        or "LiquidAI/LFM3-1.7B-GGUF",
        model_file=os.getenv("NOVA_LLM_MODEL_FILE", "LFM3-1.7B-Q4_K_M.gguf").strip()
        or "LFM3-1.7B-Q4_K_M.gguf",
        cache_dir=llm_cache_dir,
        context_tokens=max(512, int(os.getenv("NOVA_LLM_CONTEXT_TOKENS", "4096"))),
        gpu_layers=max(0, int(os.getenv("NOVA_LLM_GPU_LAYERS", "0"))),
        threads=max(1, int(raw_threads)) if raw_threads else None,
        local_files_only=_parse_bool(os.getenv("NOVA_LLM_OFFLINE_ONLY"), False),
    )

    return ServerConfig(
        host=os.getenv("NOVA_ENGINE_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=int(os.getenv("NOVA_ENGINE_PORT", "8000")),
        max_upload_bytes=max(1, max_upload_mb) * 1024 * 1024,
        cors_origins=_parse_origins(os.getenv("NOVA_CORS_ORIGINS")),
        qwen_asr=qwen_asr_cfg,
        llm=llm_cfg,
    )
