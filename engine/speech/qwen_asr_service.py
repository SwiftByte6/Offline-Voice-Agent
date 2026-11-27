"""Qwen3-ASR transcription service with a persistent Hugging Face cache."""

from dataclasses import dataclass
import io
import logging
from pathlib import Path
import threading

import av
from huggingface_hub import snapshot_download
import numpy as np
import torch
from qwen_asr import Qwen3ASRModel

from engine.config import QwenASRConfig

logger = logging.getLogger("nova.qwen_asr")


class ModelLoadingError(RuntimeError):
    """Raised when transcription is requested while the model is initializing."""


class ModelUnavailableError(RuntimeError):
    """Raised when Qwen3-ASR failed to load or is unloaded."""


class InvalidAudioError(ValueError):
    """Raised when the uploaded audio file is empty, unreadable, or corrupt."""


class TranscriptionError(RuntimeError):
    """Raised when Qwen3-ASR fails during inference."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str | None
    duration: float


def _decode_audio_to_float32(path: Path, sampling_rate: int = 16000) -> np.ndarray:
    """Decode an uploaded audio container to a mono 16 kHz waveform."""
    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=sampling_rate)
    raw_buffer = io.BytesIO()

    try:
        with av.open(str(path), mode="r") as container:
            if not any(stream.type == "audio" for stream in container.streams):
                raise InvalidAudioError("Audio file does not contain an audio stream.")
            for frame in container.decode(audio=0):
                frame.pts = None
                for resampled in resampler.resample(frame):
                    raw_buffer.write(resampled.to_ndarray())
            for resampled in resampler.resample(None):
                raw_buffer.write(resampled.to_ndarray())
    except InvalidAudioError:
        raise
    except Exception as exc:
        raise InvalidAudioError(f"Invalid or unreadable audio file: {exc}") from exc

    if raw_buffer.tell() == 0:
        raise InvalidAudioError("Audio recording contains no playable audio frames.")

    audio_s16 = np.frombuffer(raw_buffer.getbuffer(), dtype=np.int16)
    return audio_s16.astype(np.float32) / 32768.0


def _resolve_torch_dtype(value: str) -> torch.dtype:
    supported = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}
    try:
        return supported[value.lower()]
    except KeyError as exc:
        choices = ", ".join(supported)
        raise ValueError(f"Unsupported NOVA_QWEN_ASR_DTYPE '{value}'. Use: {choices}.") from exc


class QwenASRService:
    """Manages one Qwen3-ASR model for the application lifecycle."""

    def __init__(self, config: QwenASRConfig) -> None:
        self.config = config
        self._model: Qwen3ASRModel | None = None
        self._status = "unloaded"
        self._error: str | None = None
        self._init_lock = threading.Lock()

    @property
    def status(self) -> str:
        return self._status

    @property
    def ready(self) -> bool:
        return self._status == "ready" and self._model is not None

    @property
    def error(self) -> str | None:
        return self._error

    def load_model(self) -> None:
        """Load Qwen3-ASR once, downloading weights into the configured cache if needed."""
        with self._init_lock:
            if self.ready:
                return
            self._status = "loading"
            self._error = None
            try:
                self.config.cache_dir.mkdir(parents=True, exist_ok=True)
                model_path = self._resolve_model_path()
                logger.info(
                    "Initializing Qwen3-ASR model=%s device=%s dtype=%s cache_dir=%s",
                    self.config.model_name, self.config.device, self.config.dtype, self.config.cache_dir,
                )
                self._model = Qwen3ASRModel.from_pretrained(
                    model_path,
                    device_map=self.config.device,
                    dtype=_resolve_torch_dtype(self.config.dtype),
                    max_inference_batch_size=1,
                    max_new_tokens=self.config.max_new_tokens,
                )
                self._status = "ready"
                logger.info("Qwen3-ASR model '%s' is ready.", self.config.model_name)
            except Exception as exc:
                self._model = None
                self._status = "error"
                self._error = str(exc)
                logger.exception("Failed to initialize Qwen3-ASR model.")

    def _resolve_model_path(self) -> str:
        """Return a local model directory, downloading the configured Hub model when allowed."""
        configured_path = Path(self.config.model_name).expanduser()
        if configured_path.is_dir():
            return str(configured_path.resolve())

        model_dir = self.config.cache_dir / "model"
        if (model_dir / "config.json").is_file():
            return str(model_dir)
        if self.config.local_files_only:
            raise FileNotFoundError(
                f"Qwen3-ASR weights are not cached in {model_dir}. "
                "Start once without NOVA_QWEN_ASR_OFFLINE_ONLY to download them."
            )

        logger.info("Downloading Qwen3-ASR weights for '%s' to %s...", self.config.model_name, model_dir)
        return snapshot_download(repo_id=self.config.model_name, local_dir=str(model_dir))

    def transcribe_file(self, audio_path: str | Path) -> TranscriptionResult:
        """Transcribe one audio file synchronously in the worker thread."""
        if self._status == "loading":
            raise ModelLoadingError("Speech model is still loading. Please wait a moment.")
        if not self.ready or self._model is None:
            raise ModelUnavailableError(self._error or "Speech model is not loaded.")
        path = Path(audio_path)
        if not path.is_file() or path.stat().st_size == 0:
            raise InvalidAudioError("Audio file is empty or missing.")

        audio = _decode_audio_to_float32(path)
        duration = round(len(audio) / 16000, 2)
        try:
            result = self._model.transcribe(audio=(audio, 16000), language=self.config.language)[0]
        except Exception as exc:
            raise TranscriptionError(f"Transcription failed: {exc}") from exc

        return TranscriptionResult(
            text=(result.text or "").strip(),
            language=getattr(result, "language", None),
            duration=duration,
        )
