"""SpeechGate: cut utterances out of a continuous 16 kHz PCM stream (Jarvis-style)."""

from __future__ import annotations

import array
import math

RATE = 16000
GATE_ONSET_S = 0.24
GATE_PREROLL_S = 0.5
GATE_END_S = 0.7
GATE_MAX_S = 8.0
GATE_MIN_LEVEL = 110.0


def rms(chunk: bytes) -> float:
    a = array.array("h", chunk)
    return math.sqrt(sum(x * x for x in a) / len(a)) if a else 0.0


class SpeechGate:
    """Tracks room noise floor; starts on onset keeping preroll; ends after quiet or max length."""

    def __init__(self) -> None:
        self.floor = 60.0
        self.reset()

    def reset(self) -> None:
        self.pre: list[bytes] = []
        self.frames: list[bytes] = []
        self.loud = 0.0
        self.quiet = 0.0
        self.active = False

    def threshold(self) -> float:
        return max(GATE_MIN_LEVEL, self.floor * 2.5)

    def feed(self, chunk: bytes, level: float | None = None) -> bytes | None:
        level = rms(chunk) if level is None else level
        secs = len(chunk) / 2 / RATE
        loud = level > self.threshold()
        if not self.active:
            if loud:
                self.loud += secs
            else:
                self.floor += (level - self.floor) * 0.05
                self.loud = 0.0
            self.pre.append(chunk)
            while len(self.pre) * secs > GATE_PREROLL_S + GATE_ONSET_S:
                self.pre.pop(0)
            if self.loud >= GATE_ONSET_S:
                self.active = True
                self.frames = self.pre
                self.pre = []
                self.quiet = 0.0
            return None
        self.frames.append(chunk)
        self.quiet = 0.0 if loud else self.quiet + secs
        if self.quiet >= GATE_END_S or len(self.frames) * secs >= GATE_MAX_S:
            pcm = b"".join(self.frames)
            self.reset()
            return pcm
        return None
