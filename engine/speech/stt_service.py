"""Unified offline STT service for P.E.K.K.A (Jarvis-style Parakeet primary + Whisper fallback)."""

from __future__ import annotations

import logging
from pathlib import Path

from engine.config import ParakeetConfig, WhisperConfig
from engine.speech.parakeet_service import (
    InvalidAudioError,
    ModelLoadingError,
    ModelUnavailableError,
    ParakeetService,
    TranscriptionError,
    TranscriptionResult,
)
from engine.speech.transcript import clean_transcript
from engine.speech.whisper_service import WhisperService

logger = logging.getLogger("pekka.stt")


class OfflineSTTService:
    """Jarvis-style STT: NVIDIA Parakeet (sherpa-onnx) primary, Faster-Whisper offline fallback."""

    def __init__(self, parakeet_cfg: ParakeetConfig, whisper_cfg: WhisperConfig) -> None:
        self.parakeet = ParakeetService(parakeet_cfg)
        self.whisper = WhisperService(whisper_cfg)

    def load_model(self) -> None:
        """Load Parakeet first; also load cached Whisper for multilingual/fallback use."""
        self.parakeet.load_model()
        if self.parakeet.ready:
            if self.whisper.config.cache_dir.exists():
                self.whisper.load_model()
            return
        logger.warning("Parakeet unavailable (%s); loading Faster-Whisper fallback...", self.parakeet.error)
        self.whisper.load_model()

    @property
    def status(self) -> str:
        if self.parakeet.ready or self.whisper.ready:
            return "ready"
        if self.parakeet.status == "loading" or self.whisper.status == "loading":
            return "loading"
        if self.parakeet.status == "error" and self.whisper.status == "error":
            return "error"
        return "unloaded"

    @property
    def ready(self) -> bool:
        return self.parakeet.ready or self.whisper.ready

    @property
    def model_name(self) -> str:
        if self.parakeet.ready:
            return self.parakeet.model_name
        if self.whisper.ready:
            return f"whisper-{self.whisper.config.model_name}"
        return self.parakeet.model_name

    @property
    def error(self) -> str | None:
        if self.ready:
            return None
        return self.parakeet.error or self.whisper.error

    def _pick_backend(self, language: str | None, preferred: str | None = None) -> str:
        pref = (preferred or "").strip().lower()
        if pref == "whisper" and self.whisper.ready:
            return "whisper"
        if pref == "parakeet" and self.parakeet.ready:
            return "parakeet"
        non_english = bool(language and language.lower() not in {"en", "en-us", "en-gb"})
        if non_english and self.whisper.ready:
            return "whisper"
        if self.parakeet.ready and not non_english:
            return "parakeet"
        if self.whisper.ready:
            return "whisper"
        if self.status == "loading":
            raise ModelLoadingError("Speech model is still loading. Please wait a moment.")
        raise ModelUnavailableError(self.error or "No offline speech model is loaded.")

    def transcribe_file(
        self,
        audio_path: str | Path,
        *,
        language: str | None = None,
        strip_name: bool = False,
        preferred_engine: str | None = None,
    ) -> TranscriptionResult:
        backend = self._pick_backend(language, preferred_engine)
        if backend == "parakeet":
            return self.parakeet.transcribe_file(audio_path, strip_name=strip_name)
        res = self.whisper.transcribe_file(audio_path, language=language)
        cleaned = clean_transcript(res.text, strip_name=strip_name, wake_name="P.E.K.K.A")
        return TranscriptionResult(text=cleaned, language=res.language, duration=res.duration)

    def transcribe_pcm(
        self,
        pcm: bytes,
        *,
        language: str | None = None,
        strip_name: bool = False,
        preferred_engine: str | None = None,
    ) -> TranscriptionResult:
        backend = self._pick_backend(language, preferred_engine)
        if backend == "parakeet":
            return self.parakeet.transcribe_pcm(pcm, strip_name=strip_name)
        res = self.whisper.transcribe_pcm(pcm, language=language)
        cleaned = clean_transcript(res.text, strip_name=strip_name, wake_name="P.E.K.K.A")
        return TranscriptionResult(text=cleaned, language=res.language, duration=res.duration)
