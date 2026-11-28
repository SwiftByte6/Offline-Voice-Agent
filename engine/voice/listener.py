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
from engine.voice.wakeword import (
    CHUNK,
    DEFAULT_WAKE_MODEL,
    EMBEDDING,
    FALLBACK_WAKE_MODEL,
    JARVIS_WAKE_MODEL,
    MELSPECTROGRAM,
    WakeWord,
)

logger = logging.getLogger("pekka.listener")


def _default_wake_dir() -> Path:
    local = Path(__file__).resolve().parent.parent / ".cache" / "wakeword"
    jarvis_dl = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "JARVIS" / "voice" / "downloads"
    required = (MELSPECTROGRAM, EMBEDDING)
    wake_models = (os.getenv("PEKKA_WAKE_MODEL", DEFAULT_WAKE_MODEL), FALLBACK_WAKE_MODEL, JARVIS_WAKE_MODEL)
    for folder in (local, jarvis_dl):
        if folder.is_dir() and all((folder / name).is_file() for name in required) and any(
            (folder / name).is_file() for name in wake_models
        ):
            return folder
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
        self.last_wake_at: float = 0.0
        self.last_error: str | None = None
        self.event_id = 0
        self.event: dict[str, Any] = {"id": 0, "phase": "idle", "transcript": "", "response_text": "", "error": None}

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._busy = threading.Lock()
        self._hearing = threading.Lock()
        self._quiet_until = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._capture_requested = threading.Event()

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> dict[str, Any]:
        if self._thread is not None and self._thread.is_alive():
            return self.status()
        self._loop = loop
        self._stop.clear()
        self.enabled = True
        self.state = "listening"
        self.last_error = None
        self._publish("idle", transcript="")
        self._thread = threading.Thread(target=self._wake_loop, args=(self._stop,), daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        self.enabled = False
        self.state = "idle"
        self._capture_requested.clear()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        if thread is None or not thread.is_alive():
            self._thread = None
        self._publish("idle", transcript="")
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "state": self.state,
            "wake_name": self.wake_name,
            "any_speech": self.any_speech,
            "wakeword_active": self.wakeword_active,
            "wake_mode": "openwakeword" if self.wakeword_active else "speech_fallback",
            "last_transcript": self.last_transcript,
            "last_wake_at": self.last_wake_at,
            "last_error": self.last_error,
            "event": dict(self.event),
        }

    def _publish(self, phase: str, *, transcript: str = "", response_text: str = "", error: str | None = None) -> None:
        self.event_id += 1
        self.event = {
            "id": self.event_id,
            "phase": phase,
            "transcript": transcript,
            "response_text": response_text,
            "error": error,
        }

    def complete_turn(self, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        """Publish the completed agent response and release the listener for the next wake."""
        response = str((result or {}).get("response_text") or "")
        transcript = str((result or {}).get("transcript") or self.last_transcript or "")
        errors = (result or {}).get("errors") or []
        detail = error or ("; ".join(map(str, errors)) if errors else None)
        self.last_error = detail
        self.state = "listening" if self.enabled else "idle"
        self._publish("error" if error else "success", transcript=transcript, response_text=response, error=detail)
        if self._busy.locked():
            self._busy.release()

    def _dispatch(self, text: str) -> None:
        self.last_transcript = text
        self.last_wake_at = time.time()
        self.state = "processing"
        self._publish("processing", transcript=text)
        if self.on_transcript is None:
            self.complete_turn({"transcript": text, "response_text": text})
            return
        res = self.on_transcript(text)
        if asyncio.iscoroutine(res) and self._loop is not None:
            future = asyncio.run_coroutine_threadsafe(res, self._loop)

            def report_failure(done: Any) -> None:
                try:
                    done.result()
                except Exception as exc:  # noqa: BLE001
                    logger.error("Voice command pipeline failed: %s", exc, exc_info=(type(exc), exc, exc.__traceback__))
                    self.complete_turn(error=str(exc))

            future.add_done_callback(report_failure)
        elif asyncio.iscoroutine(res):
            res.close()
            self.complete_turn(error="Voice command event loop is unavailable.")
        elif res is not None:
            self.complete_turn(res if isinstance(res, dict) else {"transcript": text, "response_text": str(res)})
        else:
            self.complete_turn({"transcript": text, "response_text": ""})

    def _wake_loop(self, stop: threading.Event) -> None:
        try:
            import sounddevice as sd
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            self.state = "error"
            self._publish("error", error=f"Audio input unavailable: {exc}")
            logger.exception("Audio input module unavailable")
            return

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
        self.state = "listening"
        logger.info("Continuous listening started (wake_name=%s, any_speech=%s)", self.wake_name, self.any_speech)
        while not stop.is_set():
            try:
                with sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK) as mic:
                    if self.state == "error":
                        self.state = "listening"
                        self.last_error = None
                        self._publish("idle", transcript="")
                    while not stop.is_set():
                        if self._capture_requested.is_set():
                            self._capture_requested.clear()
                            self._listen_utterance(stop, mic)
                            continue
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
                self.state = "error"
                logger.warning("Microphone unavailable (%s); retrying in 3s", exc)
                self._publish("error", error=str(exc))
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
            if raw:
                logger.debug("SpeechGate heard: %r", raw)
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
                if not self._busy.acquire(blocking=False):
                    self.state = "listening"
                    return
                self._dispatch(request)
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
        self.last_transcript = "Listening..."
        self.last_wake_at = time.time()
        self.state = "listening_utterance"
        self._publish("listening", transcript="Listening...")
        self._capture_requested.set()

    def _listen_utterance(self, stop: threading.Event, stream: Any | None) -> None:
        try:
            self.state = "listening_utterance"
            pcm = record_utterance(stop, stream=stream, block=CHUNK)
            if not pcm:
                self.state = "listening" if self.enabled else "idle"
                self._publish(self.state, transcript="")
                if self._busy.locked():
                    self._busy.release()
                return
            self.state = "transcribing"
            self._publish("transcribing", transcript="Transcribing...")
            res = self.stt.transcribe_pcm(pcm, strip_name=True)
            if res.text:
                self._dispatch(res.text)
            else:
                self.state = "listening" if self.enabled else "idle"
                self._publish(self.state, transcript="")
                if self._busy.locked():
                    self._busy.release()
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            logger.exception("Utterance capture failed")
            self.state = "listening" if self.enabled else "idle"
            self._publish("error", error=str(exc))
            if self._busy.locked():
                self._busy.release()
        finally:
            if not self._busy.locked():
                self.state = "listening" if self.enabled else "idle"
