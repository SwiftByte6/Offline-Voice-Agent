"""Continuous microphone listener for P.E.K.K.A (WakeWord + SpeechGate + record_utterance + STT).

Listens continuously on the default microphone:
  1. openWakeWord (`hey_pekka_v0.1.onnx` if cached) triggers immediate utterance capture.
  2. SpeechGate (`any_speech=True`, Jarvis-style) cuts overheard utterances, transcribes them
     in-memory via `OfflineSTTService.transcribe_pcm`, and wakes whenever "Hey P.E.K.K.A" /
     "P.E.K.K.A" is spoken—even if custom openWakeWord ONNX files aren't installed yet.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable

from engine.speech.speech_gate import SpeechGate
from engine.speech.stt_service import OfflineSTTService
from engine.speech.transcript import addressed, clean_transcript
from engine.voice.audio_capture import RATE, record_utterance
from engine.voice.wakeword import CHUNK, WakeWord

logger = logging.getLogger("pekka.listener")


def _default_wake_dir() -> Path:
    local = Path(__file__).resolve().parent.parent / ".cache" / "wakeword"
    if local.is_dir():
        return local
    jarvis_dl = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "JARVIS" / "voice" / "downloads"
    if jarvis_dl.is_dir():
        return jarvis_dl
    return local


class VoiceListener:
    """Continuous offline mic listener mirroring `jarvis_agent.voice.Voice`."""

    def __init__(
        self,
        stt: OfflineSTTService,
        on_transcript: Callable[[str], Any] | None = None,
        *,
        wake_dir: Path | None = None,
        wake_name: str = "P.E.K.K.A",
        any_speech: bool = True,
    ) -> None:
        self.stt = stt
        self.on_transcript = on_transcript
        self.wake_dir = wake_dir or _default_wake_dir()
        self.wake_name = wake_name
        self.any_speech = any_speech

        self.enabled = False
        self.state = "idle"
        self.wakeword_active = False
        self.last_transcript: str = ""
        self.last_error: str | None = None

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._busy = threading.Lock()
        self._hearing = threading.Lock()
        self._quiet_until = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> dict[str, Any]:
        if self._thread is not None and self._thread.is_alive():
            return self.status()
        self._loop = loop
        self._stop.clear()
        self.enabled = True
        self.state = "listening"
        self.last_error = None
        self._thread = threading.Thread(target=self._wake_loop, args=(self._stop,), daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        self.enabled = False
        self.state = "idle"
        self._thread = None
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "state": self.state,
            "wake_name": self.wake_name,
            "any_speech": self.any_speech,
            "wakeword_active": self.wakeword_active,
            "last_transcript": self.last_transcript,
            "last_error": self.last_error,
        }

    def _dispatch(self, text: str) -> None:
        self.last_transcript = text
        if self.on_transcript is None:
            return
        res = self.on_transcript(text)
        if asyncio.iscoroutine(res) and self._loop is not None:
            asyncio.run_coroutine_threadsafe(res, self._loop)

    def _wake_loop(self, stop: threading.Event) -> None:
        import sounddevice as sd

        detector: WakeWord | None = None
        if self.wake_dir.is_dir():
            try:
                detector = WakeWord(self.wake_dir)
                self.wakeword_active = True
                logger.info("openWakeWord active from %s", self.wake_dir)
            except Exception as exc:  # noqa: BLE001
                self.wakeword_active = False
                logger.info("WakeWord ONNX not loaded (%s); using SpeechGate + 'Hey %s' check", exc, self.wake_name)

        gate = SpeechGate()
        logger.info("Continuous listening started (wake_name=%s, any_speech=%s)", self.wake_name, self.any_speech)
        while not stop.is_set():
            try:
                with sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK) as mic:
                    while not stop.is_set():
                        data, _ = mic.read(CHUNK)
                        chunk = bytes(data)
                        now = time.monotonic()
                        if self._busy.locked() or now < self._quiet_until:
                            if detector is not None:
                                detector.reset()
                            gate.reset()
                            continue
                        if detector is not None:
                            score = detector.heard(chunk)
                            if score is not None:
                                logger.info("Wake word heard (%.2f)", score)
                                gate.reset()
                                self._quiet_until = now + 3.0
                                self._on_wake()
                                continue
                        if not self.any_speech or self._hearing.locked():
                            continue
                        pcm = gate.feed(chunk)
                        if pcm:
                            threading.Thread(target=self._consider, args=(pcm,), daemon=True).start()
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                logger.warning("Microphone unavailable (%s); retrying in 3s", exc)
                stop.wait(3)

    def _consider(self, pcm: bytes) -> None:
        if not self._hearing.acquire(blocking=False):
            return
        try:
            if not self.stt.ready:
                return
            self.state = "transcribing"
            res = self.stt.transcribe_pcm(pcm, strip_name=False)
            raw = res.text
            if not raw or not addressed(raw, wake_name=self.wake_name):
                self.state = "listening"
                return
            if self._busy.locked():
                self.state = "listening"
                return
            logger.info("Woken by speech naming %s: %s", self.wake_name, raw)
            self._quiet_until = time.monotonic() + 3.0
            request = clean_transcript(raw, strip_name=True, wake_name=self.wake_name)
            if len(request.split()) >= 2:
                self._dispatch(request)
                self.state = "listening"
            else:
                self._on_wake()
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            logger.exception("SpeechGate consideration failed")
            self.state = "listening"
        finally:
            self._hearing.release()

    def _on_wake(self) -> None:
        if not self._busy.acquire(blocking=False):
            return
        threading.Thread(target=self._listen_utterance, daemon=True).start()

    def _listen_utterance(self) -> None:
        try:
            self.state = "listening_utterance"
            pcm = record_utterance(self._stop)
            if not pcm:
                self.state = "listening"
                return
            self.state = "transcribing"
            res = self.stt.transcribe_pcm(pcm, strip_name=True)
            if res.text:
                self._dispatch(res.text)
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            logger.exception("Utterance capture failed")
        finally:
            self.state = "listening" if self.enabled else "idle"
            self._busy.release()
