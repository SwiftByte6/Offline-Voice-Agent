"""Piper TTS for P.E.K.K.A (Jarvis-style persistent process + sentence streaming + sounddevice stop).

Keeps one `piper.exe` process alive in `--output_dir` mode so only the first sentence pays model
load time. Auto-discovers `piper.exe` and `.onnx` voice models from `PEKKA_PIPER_EXE` /
`PEKKA_PIPER_MODEL`, `engine/.cache/piper`, or `%LOCALAPPDATA%/JARVIS/voice`. When Piper isn't
installed, Windows System.Speech provides an offline local WAV fallback.
"""

from __future__ import annotations

import base64
import io
import os
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SENTENCE_SILENCE = "0.1"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class PiperSpeechResult:
    spoken: bool
    sentences: int
    audio_base64: str | None
    audio_format: str = "wav"
    error: str | None = None
    wav_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "spoken": self.spoken,
            "sentences": self.sentences,
            "audio_base64": self.audio_base64,
            "audio_format": self.audio_format,
            "error": self.error,
            "wav_paths": list(self.wav_paths),
        }


def sentences(text: str) -> list[str]:
    """Split into sentences; keep very short ones with next; supports Hindi danda."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?…।])\s+|\n+", text) if p.strip()]
    out: list[str] = []
    for p in parts:
        if out and len(out[-1]) < 25:
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    return out


def _combine_wavs(wavs: list[bytes]) -> bytes:
    """Concatenate WAV files (same params) into one WAV."""
    if len(wavs) == 1:
        return wavs[0]
    out = io.BytesIO()
    params = None
    frames: list[bytes] = []
    for data in wavs:
        with wave.open(io.BytesIO(data), "rb") as w:
            if params is None:
                params = w.getparams()
            frames.append(w.readframes(w.getnframes()))
    with wave.open(out, "wb") as w:
        assert params is not None
        w.setparams(params)
        for f in frames:
            w.writeframes(f)
    return out.getvalue()


def _discover_piper() -> tuple[str, str]:
    """Find piper.exe and a .onnx voice model in env, engine/.cache/piper, or %LOCALAPPDATA%/JARVIS/voice."""
    exe = os.getenv("PEKKA_PIPER_EXE", "").strip()
    model = os.getenv("PEKKA_PIPER_MODEL", "").strip()
    roots = [
        Path(__file__).resolve().parent.parent / ".cache" / "piper",
        Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "JARVIS" / "voice",
    ]
    if not exe:
        for root in roots:
            if root.is_dir():
                hit = next(root.rglob("piper.exe"), None)
                if hit and hit.is_file():
                    exe = str(hit)
                    break
    if not model:
        for root in roots:
            if root.is_dir():
                hit = next((p for p in sorted(root.rglob("*.onnx")) if p.with_name(p.name + ".json").is_file()), None)
                if hit:
                    model = str(hit)
                    break
    return exe, model


class _PersistentPiper:
    """One long-running piper.exe: a line of text in, the path of its WAV out (Jarvis-style)."""

    def __init__(self, exe: str, model: str, sentence_silence: str = SENTENCE_SILENCE) -> None:
        self.exe = exe
        self.model = model
        self.sentence_silence = sentence_silence
        self.dir = Path(tempfile.mkdtemp(prefix="pekka-tts-"))
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()

    def _start(self) -> subprocess.Popen:
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen(
                [self.exe, "--model", self.model, "--output_dir", str(self.dir), "--sentence_silence", self.sentence_silence],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                cwd=str(Path(self.exe).parent),
                creationflags=_CREATE_NO_WINDOW,
            )
        return self.proc

    def synth(self, text: str) -> bytes | None:
        line = re.sub(r"\s+", " ", text).strip()
        if not line:
            return None
        with self.lock:
            for _ in range(2):
                p = self._start()
                try:
                    assert p.stdin is not None and p.stdout is not None
                    p.stdin.write(line + "\n")
                    p.stdin.flush()
                    out = p.stdout.readline().strip()
                except (OSError, ValueError):
                    out = ""
                if out and Path(out).is_file():
                    path = Path(out)
                    try:
                        return path.read_bytes()
                    finally:
                        path.unlink(missing_ok=True)
                self.close()
        return None

    def close(self) -> None:
        if self.proc is not None:
            try:
                self.proc.kill()
            except OSError:
                pass
        self.proc = None


class PiperTTS:
    """Jarvis-style persistent Piper TTS with optional local sounddevice playback + stop()."""

    def __init__(
        self,
        exe: str | None = None,
        model: str | None = None,
        sentence_silence: str | None = None,
    ) -> None:
        disc_exe, disc_model = _discover_piper()
        self.exe = exe or disc_exe
        self.model = model or disc_model
        self.system_speech_exe = (
            shutil.which("powershell.exe") or shutil.which("powershell")
        ) if os.name == "nt" else None
        self.sentence_silence = sentence_silence or os.getenv("PEKKA_PIPER_SENTENCE_SILENCE") or SENTENCE_SILENCE
        self._piper: _PersistentPiper | None = None
        self._stop_event = threading.Event()

    @property
    def available(self) -> bool:
        piper_available = bool(self.exe) and Path(self.exe).is_file() and bool(self.model) and Path(self.model).is_file()
        return piper_available or bool(self.system_speech_exe)

    @property
    def backend(self) -> str | None:
        if self.exe and Path(self.exe).is_file() and self.model and Path(self.model).is_file():
            return "piper"
        return "windows_sapi" if self.system_speech_exe else None

    def stop(self) -> None:
        """Stop any ongoing local speaker playback immediately (barge-in)."""
        self._stop_event.set()

    def close(self) -> None:
        self.stop()
        if self._piper is not None:
            self._piper.close()
            self._piper = None

    def _get_piper(self) -> _PersistentPiper:
        if self._piper is None or self._piper.exe != self.exe or self._piper.model != self.model:
            if self._piper is not None:
                self._piper.close()
            self._piper = _PersistentPiper(self.exe, self.model, self.sentence_silence)
        return self._piper

    def _synth_system_speech(self, text: str) -> bytes | None:
        """Synthesize a local WAV with the installed Windows SAPI voice as a Piper fallback."""
        if not self.system_speech_exe:
            return None
        with tempfile.TemporaryDirectory(prefix="pekka-sapi-") as temp_dir:
            wav_path = Path(temp_dir) / "speech.wav"
            script_path = Path(temp_dir) / "synthesize.ps1"
            text_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
            script_path.write_text(
                "\ufeff$ErrorActionPreference = 'Stop'\n"
                "Add-Type -AssemblyName System.Speech\n"
                "$text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([Console]::In.ReadToEnd().Trim()))\n"
                "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                "$synth.SetOutputToWaveFile($args[0])\n"
                "$synth.Speak($text)\n"
                "$synth.Dispose()\n",
                encoding="utf-8",
            )
            try:
                subprocess.run(
                    [self.system_speech_exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script_path), str(wav_path)],
                    input=text_b64 + "\n",
                    text=True,
                    encoding="ascii",
                    check=True,
                    capture_output=True,
                    timeout=120,
                    creationflags=_CREATE_NO_WINDOW,
                )
                return wav_path.read_bytes() if wav_path.is_file() else None
            except (OSError, subprocess.SubprocessError) as exc:
                raise RuntimeError(f"Windows offline speech synthesis failed: {exc}") from exc

    def _play_wav_bytes(self, wav_bytes: bytes) -> None:
        try:
            import sounddevice as sd
        except Exception:  # noqa: BLE001
            return
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            rate = w.getframerate()
            pcm = w.readframes(w.getnframes())
        step = int(rate * 0.05) * 2
        with sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16", latency="high") as stream:
            for i in range(0, len(pcm), step):
                if self._stop_event.is_set():
                    break
                stream.write(pcm[i : i + step])

    async def speak(self, text: str, *, play_local: bool = False) -> PiperSpeechResult:
        import asyncio

        parts = sentences(text)
        if not parts:
            return PiperSpeechResult(spoken=False, sentences=0, audio_base64=None, error="empty text")
        if not self.available:
            return PiperSpeechResult(
                spoken=False,
                sentences=len(parts),
                audio_base64=None,
                error="Piper not available: set PEKKA_PIPER_EXE and PEKKA_PIPER_MODEL; piper.exe not found",
            )
        self._stop_event.clear()
        wavs: list[bytes] = []
        if self.backend == "piper":
            piper = self._get_piper()
            for part in parts:
                if self._stop_event.is_set():
                    break
                wav = await asyncio.to_thread(piper.synth, part)
                if wav:
                    wavs.append(wav)
                    if play_local:
                        await asyncio.to_thread(self._play_wav_bytes, wav)
        else:
            for part in parts:
                if self._stop_event.is_set():
                    break
                try:
                    wav = await asyncio.to_thread(self._synth_system_speech, part)
                except RuntimeError as exc:
                    return PiperSpeechResult(spoken=False, sentences=len(parts), audio_base64=None, error=str(exc))
                if wav:
                    wavs.append(wav)
                    if play_local:
                        await asyncio.to_thread(self._play_wav_bytes, wav)
        if not wavs:
            return PiperSpeechResult(spoken=False, sentences=len(parts), audio_base64=None, error="Piper did not produce speech")
        combined = _combine_wavs(wavs)
        audio_base64 = base64.b64encode(combined).decode("ascii")
        return PiperSpeechResult(
            spoken=len(wavs) == len(parts),
            sentences=len(parts),
            audio_base64=audio_base64,
            error=None if len(wavs) == len(parts) else f"Piper produced {len(wavs)}/{len(parts)} sentences",
        )
