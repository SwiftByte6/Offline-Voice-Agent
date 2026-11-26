"""Reusable Faster-Whisper transcription service with persistent caching."""

from dataclasses import dataclass
import io
import logging
from pathlib import Path
import threading
from typing import Any

import av
from faster_whisper import WhisperModel
import numpy as np

from engine.config import WhisperConfig

logger = logging.getLogger("nova.whisper")


class ModelLoadingError(RuntimeError):
    """Raised when transcription is requested while the model is still initializing."""


class ModelUnavailableError(RuntimeError):
    """Raised when the Whisper model failed to load or is unloaded."""


class InvalidAudioError(ValueError):
    """Raised when the uploaded audio file is empty, unreadable, or corrupt."""


class TranscriptionError(RuntimeError):
    """Raised when Faster-Whisper fails during inference."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str | None
    duration: float


def _decode_audio_to_float32(path: Path, sampling_rate: int = 16000) -> np.ndarray:
    """Decode audio via PyAV without passing deprecated metadata_errors kwarg (PyAV >= 16 compat)."""
    resampler = av.audio.resampler.AudioResampler(
        format="s16",
        layout="mono",
        rate=sampling_rate,
    )
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


class WhisperService:
    """Manages a single Faster-Whisper model instance for the application lifecycle."""

    def __init__(self, config: WhisperConfig) -> None:
        self.config = config
        self._model: WhisperModel | None = None
        self._status: str = "unloaded"
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
        """Load the configured Faster-Whisper model once using a persistent cache directory."""
        with self._init_lock:
            if self._model is not None and self._status == "ready":
                return

            self._status = "loading"
            self._error = None

            try:
                self.config.cache_dir.mkdir(parents=True, exist_ok=True)
                logger.info(
                    "Initializing Faster-Whisper model=%s device=%s compute_type=%s cache_dir=%s",
                    self.config.model_name,
                    self.config.device,
                    self.config.compute_type,
                    self.config.cache_dir,
                )

                self._model = self._instantiate_model()
                self._status = "ready"
                logger.info("Faster-Whisper model '%s' is ready.", self.config.model_name)
            except Exception as exc:
                self._model = None
                self._status = "error"
                self._error = str(exc)
                logger.exception("Failed to initialize Faster-Whisper model.")

    def _instantiate_model(self) -> WhisperModel:
        kwargs: dict[str, Any] = {
            "device": self.config.device,
            "compute_type": self.config.compute_type,
            "download_root": str(self.config.cache_dir),
        }

        if self.config.local_files_only:
            return WhisperModel(self.config.model_name, local_files_only=True, **kwargs)

        # Prefer already-cached weights first so offline runs never wait on network lookups.
        try:
            return WhisperModel(self.config.model_name, local_files_only=True, **kwargs)
        except Exception:
            logger.info(
                "Cached weights not found locally for '%s'; downloading to %s...",
                self.config.model_name,
                self.config.cache_dir,
            )
            return WhisperModel(self.config.model_name, local_files_only=False, **kwargs)

    def transcribe_file(self, audio_path: str | Path) -> TranscriptionResult:
        """Transcribe an audio file synchronously (designed to be called in a worker thread)."""
        if self._status == "loading":
            raise ModelLoadingError("Speech model is still loading. Please wait a moment.")
        if not self.ready or self._model is None:
            detail = self._error or "Speech model is not loaded."
            raise ModelUnavailableError(detail)

        path = Path(audio_path)
        if not path.is_file() or path.stat().st_size == 0:
            raise InvalidAudioError("Audio file is empty or missing.")

        audio = _decode_audio_to_float32(path, sampling_rate=16000)

        try:
            segments, info = self._model.transcribe(
                audio,
                language=self.config.language,
                task=self.config.task,
                vad_filter=self.config.vad_filter,
            )
            collected = [segment.text.strip() for segment in segments if segment.text.strip()]
        except Exception as exc:
            raise TranscriptionError(f"Transcription failed: {exc}") from exc

        transcript = " ".join(collected).strip()
        duration = round(float(getattr(info, "duration", 0.0) or 0.0), 2)
        language = getattr(info, "language", None)

        return TranscriptionResult(
            text=transcript,
            language=language,
            duration=duration,
        )
