"""Jarvis-style STT: NVIDIA Parakeet via sherpa-onnx (local CPU int8)."""

from __future__ import annotations

from dataclasses import dataclass
import io
import logging
import os
from pathlib import Path
import tarfile
import threading
from typing import Any
import urllib.request

import av
import numpy as np

from engine.config import ParakeetConfig
from engine.speech.transcript import clean_transcript

logger = logging.getLogger("pekka.asr")

RATE = 16000
DEFAULT_MODEL = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
SMALL_MODEL = "sherpa-onnx-nemo-parakeet_tdt_ctc_110m-en-36000-int8"
ARCHIVES = (DEFAULT_MODEL + ".tar.bz2", SMALL_MODEL + ".tar.bz2")
DEFAULT_MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/" + DEFAULT_MODEL + ".tar.bz2"


class ModelLoadingError(RuntimeError):
    """Raised when transcription is requested while the model is still initializing."""


class ModelUnavailableError(RuntimeError):
    """Raised when Parakeet failed to load or is unloaded."""


class InvalidAudioError(ValueError):
    """Raised when uploaded audio is empty/unreadable/corrupt."""


class TranscriptionError(RuntimeError):
    """Raised when sherpa-onnx transcription fails."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str | None
    duration: float


def _decode_audio_to_float32(path: Path, sampling_rate: int = RATE) -> np.ndarray:
    """Decode audio via PyAV to mono float32 at 16 kHz."""
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


def _normalise(samples: np.ndarray, target_peak: float = 20000.0) -> np.ndarray:
    """Boost quiet speech up to 30x before sherpa-onnx (Jarvis-style normalise)."""
    if samples.size == 0:
        return samples
    target_float = target_peak / 32768.0
    peak_float = float(np.max(np.abs(samples)))
    if peak_float == 0 or peak_float >= target_float:
        return samples
    gain = min(30.0, target_float / peak_float)
    return np.clip(samples * gain, -1.0, 1.0).astype(np.float32)


def _unpack_archive(src: Path, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(src, "r:bz2") as tar:
        tar.extractall(root, filter="data")


def _is_model_dir(folder: Path) -> bool:
    return (folder / "tokens.txt").is_file()


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class ParakeetService:
    """One sherpa-onnx NVIDIA Parakeet model, kept loaded; thread-safe."""

    def __init__(self, config: ParakeetConfig) -> None:
        self.config = config
        self._model: Any | None = None
        self._status = "unloaded"
        self._error: str | None = None
        self._init_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self.model_name: str = "NVIDIA Parakeet"

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
        """Load Parakeet once. Models are local; first launch may download archive if not offline-only."""
        with self._init_lock:
            if self.ready:
                return
            self._status = "loading"
            self._error = None
            try:
                import sherpa_onnx  # noqa: F401

                folder = self._resolve_model_path()
                self._model = self._instantiate(folder)
                self.model_name = folder.name
                self._status = "ready"
                logger.info("speech recognition: NVIDIA %s", self.model_name)
            except Exception as exc:  # noqa: BLE001
                self._model = None
                self._status = "error"
                self._error = str(exc)
                logger.exception("Parakeet could not load.")

    def _instantiate(self, folder: Path) -> Any:
        import sherpa_onnx

        threads = max(2, min(4, os.cpu_count() or 2))
        enc = next(iter(sorted(folder.glob("encoder*.onnx"))), None)
        if enc is not None:
            return sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(enc),
                decoder=str(next(folder.glob("decoder*.onnx"))),
                joiner=str(next(folder.glob("joiner*.onnx"))),
                tokens=str(folder / "tokens.txt"),
                num_threads=threads,
                model_type="nemo_transducer",
                decoding_method="greedy_search",
            )
        model = next(iter(sorted(folder.glob("model*.onnx"))))
        return sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
            model=str(model),
            tokens=str(folder / "tokens.txt"),
            num_threads=threads,
        )

    def _resolve_model_path(self) -> Path:
        for env_name in ("PEKKA_PARAKEET_MODEL", "PEKKA_PARAKEET_MODEL_DIR", "PEKKA_ASR_MODEL"):
            raw = os.getenv(env_name) or (self.config.model_name if env_name == "PEKKA_PARAKEET_MODEL" else None)
            if raw:
                p = Path(raw).expanduser()
                if p.is_dir() and _is_model_dir(p):
                    return p.resolve()
                if p.is_file() and p.name.endswith(".tar.bz2"):
                    root = self.config.cache_dir / "parakeet"
                    _unpack_archive(p, root)
                    folder = root / p.name.removesuffix(".tar.bz2")
                    if _is_model_dir(folder):
                        return folder.resolve()

        cache = self.config.cache_dir
        root = cache / "parakeet"
        model_name = self.config.model_name or DEFAULT_MODEL
        for folder in (root / model_name, cache / model_name, root / DEFAULT_MODEL, cache / DEFAULT_MODEL, root / SMALL_MODEL, cache / SMALL_MODEL):
            if _is_model_dir(folder):
                return folder.resolve()
        for archive_name in ARCHIVES:
            src = cache / "downloads" / archive_name
            if src.is_file():
                _unpack_archive(src, root)
                folder = root / archive_name.removesuffix(".tar.bz2")
                if _is_model_dir(folder):
                    return folder.resolve()

        if self.config.local_files_only or _bool(os.getenv("PEKKA_PARAKEET_OFFLINE_ONLY"), False):
            raise FileNotFoundError(
                f"Parakeet weights not cached under {root / model_name}."
            )

        archive_name = model_name if model_name.endswith(".tar.bz2") else model_name + ".tar.bz2"
        url = os.getenv("PEKKA_PARAKEET_MODEL_URL") or DEFAULT_MODEL_URL
        downloads = cache / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        archive_path = downloads / Path(archive_name).name
        if not archive_path.is_file():
            logger.info("Downloading Parakeet model %s -> %s", url, archive_path)
            urllib.request.urlretrieve(url, archive_path)
        _unpack_archive(archive_path, root)
        folder = root / archive_name.removesuffix(".tar.bz2")
        if not _is_model_dir(folder):
            for candidate in root.rglob("tokens.txt"):
                return candidate.parent.resolve()
            raise FileNotFoundError(f"Downloaded model missing tokens.txt in {folder}")
        return folder.resolve()

    def _transcribe_samples(self, samples: np.ndarray, *, strip_name: bool = False) -> TranscriptionResult:
        if samples.size == 0:
            raise InvalidAudioError("Audio recording contains no playable audio frames.")
        audio = _normalise(samples)
        duration = round(len(audio) / RATE, 2)
        padded = np.concatenate([np.zeros(int(0.2 * RATE), np.float32), audio.astype(np.float32), np.zeros(int(0.3 * RATE), np.float32)])
        try:
            with self._infer_lock:
                stream = self._model.create_stream()
                stream.accept_waveform(RATE, padded)
                self._model.decode_stream(stream)
                text = stream.result.text.strip()
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError(f"Transcription failed: {exc}") from exc

        cleaned = clean_transcript(text, strip_name=strip_name, wake_name="P.E.K.K.A")
        return TranscriptionResult(text=cleaned, language="en", duration=duration)

    def transcribe_pcm(self, pcm: bytes, *, strip_name: bool = False) -> TranscriptionResult:
        """Transcribe raw 16 kHz mono int16 PCM bytes in-memory."""
        if self._status == "loading":
            raise ModelLoadingError("Speech model is still loading. Please wait a moment.")
        if not self.ready or self._model is None:
            raise ModelUnavailableError(self._error or "Speech model is not loaded.")
        if not pcm:
            raise InvalidAudioError("Audio buffer is empty.")
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        return self._transcribe_samples(samples, strip_name=strip_name)

    def transcribe_file(self, audio_path: str | Path, *, strip_name: bool = False) -> TranscriptionResult:
        """Transcribe an audio file synchronously."""
        if self._status == "loading":
            raise ModelLoadingError("Speech model is still loading. Please wait a moment.")
        if not self.ready or self._model is None:
            raise ModelUnavailableError(self._error or "Speech model is not loaded.")

        path = Path(audio_path)
        if not path.is_file() or path.stat().st_size == 0:
            raise InvalidAudioError("Audio file is empty or missing.")

        samples = _decode_audio_to_float32(path)
        return self._transcribe_samples(samples, strip_name=strip_name)
