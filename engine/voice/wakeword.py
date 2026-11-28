"""openWakeWord detector for P.E.K.K.A (local onnxruntime, Jarvis-style)."""

from __future__ import annotations

from collections import deque
import logging
import os
from pathlib import Path

CHUNK = 1280  # 80 ms at 16 kHz
_MEL_WINDOW = 12800
_EMBEDDINGS = 16
THRESHOLD = 0.5
RATE = 16000

MELSPECTROGRAM = "melspectrogram.onnx"
EMBEDDING = "embedding_model.onnx"
DEFAULT_WAKE_MODEL = "hey_pekka_v0.1.onnx"
FALLBACK_WAKE_MODEL = "hey_pekka.onnx"
JARVIS_WAKE_MODEL = "hey_jarvis_v0.1.onnx"

WAKE_NAME = os.getenv("PEKKA_WAKE_NAME", "P.E.K.K.A")
logger = logging.getLogger("pekka.wakeword")


def wake_model_name() -> str:
    return os.getenv("PEKKA_WAKE_MODEL", DEFAULT_WAKE_MODEL)


class WakeWord:
    """openWakeWord pipeline; one new embedding per 80 ms chunk; score over last ~1.3 s."""

    def __init__(self, folder: Path, threshold: float = THRESHOLD, wake_model: str | None = None) -> None:
        import numpy as np
        import onnxruntime as ort

        self.np = np
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1

        wake = wake_model or wake_model_name()
        if not (folder / wake).is_file():
            if (folder / FALLBACK_WAKE_MODEL).is_file():
                wake = FALLBACK_WAKE_MODEL
            elif (folder / JARVIS_WAKE_MODEL).is_file():
                logger.warning("Custom wake model %s not found; using %s", wake, JARVIS_WAKE_MODEL)
                wake = JARVIS_WAKE_MODEL
            else:
                raise FileNotFoundError(f"No wake-word model found in {folder}")

        if not ((folder / MELSPECTROGRAM).is_file() and (folder / EMBEDDING).is_file()):
            raise FileNotFoundError(f"Missing {MELSPECTROGRAM} or {EMBEDDING} in {folder}")

        self.mel = ort.InferenceSession(str(folder / MELSPECTROGRAM), sess_options=opts, providers=["CPUExecutionProvider"])
        self.emb = ort.InferenceSession(str(folder / EMBEDDING), sess_options=opts, providers=["CPUExecutionProvider"])
        self.wake = ort.InferenceSession(str(folder / wake), sess_options=opts, providers=["CPUExecutionProvider"])
        self.mel_in = self.mel.get_inputs()[0].name
        self.emb_in = self.emb.get_inputs()[0].name
        self.wake_in = self.wake.get_inputs()[0].name
        self.threshold = threshold
        self.reset()

    def reset(self) -> None:
        self.audio = self.np.zeros(_MEL_WINDOW, dtype=self.np.float32)
        self.embeddings: deque = deque(maxlen=_EMBEDDINGS)
        self.cooldown = 0

    def process(self, chunk: bytes) -> float:
        np = self.np
        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
        self.audio = np.concatenate([self.audio, samples])[-_MEL_WINDOW:]
        spec = np.squeeze(self.mel.run(None, {self.mel_in: self.audio[None, :]})[0]) / 10.0 + 2.0
        spec = spec[-76:]
        if spec.shape[0] < 76:
            return 0.0
        emb = self.emb.run(None, {self.emb_in: spec[None, :, :, None].astype(np.float32)})[0]
        self.embeddings.append(np.squeeze(emb))
        if len(self.embeddings) < _EMBEDDINGS:
            return 0.0
        score = float(np.squeeze(self.wake.run(None, {self.wake_in: np.stack(self.embeddings)[None, :, :].astype(np.float32)})[0]))
        if self.cooldown:
            self.cooldown -= 1
            return 0.0
        return score

    def heard(self, chunk: bytes) -> float | None:
        score = self.process(chunk)
        if score >= self.threshold:
            self.cooldown = 18
            return score
        return None
