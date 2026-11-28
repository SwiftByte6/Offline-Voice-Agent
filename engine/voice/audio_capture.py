"""Audio capture helpers for P.E.K.K.A (16 kHz mono int16 via sounddevice, Jarvis-style)."""

from __future__ import annotations

import array
import io
import math
import threading
import time
from typing import Callable
import wave

from engine.speech.speech_gate import RATE, SpeechGate

NO_SPEECH_S = 5.0
END_SILENCE_S = 0.75
MAX_UTTERANCE_S = 15.0


def _rms(chunk: bytes) -> float:
    a = array.array("h", chunk)
    return math.sqrt(sum(x * x for x in a) / len(a)) if a else 0.0


def normalise(pcm: bytes, target_peak: int = 20000) -> bytes:
    """Bring quiet speech up to healthy level, at most 30x."""
    a = array.array("h", pcm)
    peak = max((abs(x) for x in a), default=0)
    if not peak or peak >= target_peak:
        return pcm
    gain = min(30.0, target_peak / peak)
    return array.array("h", (max(-32768, min(32767, int(x * gain))) for x in a)).tobytes()


def to_wav(pcm: bytes) -> bytes:
    pcm = normalise(pcm)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def record_utterance(stop: threading.Event, on_audio: Callable[[bytes], None] | None = None) -> bytes | None:
    """Record default microphone 16 kHz mono int16 until speaker pauses."""
    import sounddevice as sd

    frames: list[bytes] = []
    block = int(RATE * 0.05)
    noise: list[float] = []
    spoken = False
    loud_for = 0.0
    quiet_for = 0.0
    started = time.monotonic()
    with sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=block) as stream:
        while not stop.is_set():
            data, _ = stream.read(block)
            data = bytes(data)
            if on_audio:
                on_audio(data)
            level = _rms(data)
            elapsed = time.monotonic() - started
            if elapsed < 0.3:
                noise.append(level)
                continue
            threshold = max(110.0, (sum(noise) / max(1, len(noise))) * 2.5)
            frames.append(data)
            if level > threshold:
                loud_for += 0.05
                quiet_for = 0.0
                if loud_for >= 0.3:
                    spoken = True
            else:
                quiet_for += 0.05
            if spoken and quiet_for >= END_SILENCE_S:
                break
            if not spoken and elapsed >= NO_SPEECH_S:
                return None
            if elapsed >= MAX_UTTERANCE_S:
                break
    return b"".join(frames) if spoken else None


def make_gate() -> SpeechGate:
    return SpeechGate()
