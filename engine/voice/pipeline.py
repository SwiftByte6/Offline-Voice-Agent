"""P.E.K.K.A offline voice-to-action pipeline (STT -> Memory/LLM -> Permission -> Tool)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from engine.speech.transcript import addressed, clean_transcript
from .intent import (
    INTENT_SYSTEM,
    Intent,
    _coerce_intent,
    detect_intent,
    is_approval_phrase,
    is_cancel_phrase,
    noop_intent,
    offline_fallback_intent,
)
from .local_llm import LocalLLM, LocalLLMUnavailable, make_local_llm
from .memory import SessionMemory
from .permissions import PermissionDecision, PermissionLayer
from .piper_tts import PiperSpeechResult, PiperTTS
from .tools import ToolExecutionError, ToolExecutor


@dataclass(frozen=True)
class PekkaPipelineResult:
    transcript: str
    intent: Intent
    permission: PermissionDecision
    tool_result: dict[str, Any] | None
    response_text: str
    spoken: PiperSpeechResult | None
    require_wake_word: bool
    wake_triggered: bool
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "transcript": self.transcript,
            "intent": {
                "intent": self.intent.intent,
                "tool": self.intent.tool,
                "response_text": self.intent.response_text,
                "requires_approval": self.intent.requires_approval,
                "reason": self.intent.reason,
            },
            "permission": {
                "allowed": self.permission.allowed,
                "needs_approval": self.permission.needs_approval,
                "blocked": self.permission.blocked,
                "reason": self.permission.reason,
            },
            "tool_result": self.tool_result,
            "response_text": self.response_text,
            "spoken": self.spoken.to_dict() if self.spoken else None,
            "require_wake_word": self.require_wake_word,
            "wake_triggered": self.wake_triggered,
            "errors": list(self.errors),
        }


class PekkaPipeline:
    """Offline voice-to-action pipeline with Jarvis-style local LLM, memory, approval gate, and Piper TTS."""

    def __init__(
        self,
        stt: Any,
        llm: LocalLLM | None | Any = ...,
        tts: PiperTTS | None = None,
        permissions: PermissionLayer | None = None,
        tools: ToolExecutor | None = None,
        memory: SessionMemory | None = None,
        wake_name: str = "P.E.K.K.A",
    ) -> None:
        self.stt = stt
        self.llm = make_local_llm() if llm is ... else llm
        self.tts = tts or PiperTTS()
        self.permissions = permissions or PermissionLayer()
        self.tools = tools or ToolExecutor()
        self.memory = memory or SessionMemory()
        self.wake_name = wake_name
        self._pending_intent: Intent | None = None

    def pending_summary(self) -> dict[str, Any] | None:
        if self._pending_intent is None:
            return None
        return {
            "intent": self._pending_intent.intent,
            "tool": self._pending_intent.tool,
            "reason": self._pending_intent.reason,
        }

    async def _transcribe_audio(self, audio_path: str | Path, language: str | None) -> Any:
        try:
            return await asyncio.to_thread(self.stt.transcribe_file, str(audio_path), language=language, strip_name=False)
        except TypeError:
            return await asyncio.to_thread(self.stt.transcribe_file, str(audio_path))

    async def run(
        self,
        *,
        audio_path: str | Path | None = None,
        transcript: str | None = None,
        speak: bool = False,
        play_local: bool = False,
        approval: bool = False,
        require_wake_word: bool = False,
        wake_name: str | None = None,
        language: str | None = None,
    ) -> PekkaPipelineResult:
        errors: list[str] = []
        wake_name = wake_name or self.wake_name

        # 1) STT
        raw_text = transcript
        if raw_text is None:
            if audio_path is None:
                raw_text = ""
                errors.append("no audio_path or transcript")
            else:
                stt_result = await self._transcribe_audio(audio_path, language)
                raw_text = stt_result.text
                if language is None:
                    language = getattr(stt_result, "language", None)

        # 2) Clean & wake check
        cleaned = clean_transcript(raw_text or "", strip_name=True, wake_name=wake_name)
        wake_triggered = addressed(cleaned, wake_name=wake_name) or addressed(raw_text or "", wake_name=wake_name)
        if require_wake_word and not wake_triggered:
            return PekkaPipelineResult(
                transcript=cleaned,
                intent=noop_intent(cleaned, ""),
                permission=PermissionDecision(True, False, False, "no wake word"),
                tool_result=None,
                response_text="",
                spoken=None,
                require_wake_word=require_wake_word,
                wake_triggered=False,
                errors=tuple(errors + ["wake word not triggered"]),
            )

        # 3) Two-turn approval ("Yes, go ahead" / "Cancel")
        if self._pending_intent is not None:
            if is_approval_phrase(cleaned):
                pending = self._pending_intent
                self._pending_intent = None
                permission = self.permissions.check(pending, approval=True)
                tool_result = None
                if pending.tool is not None and permission.allowed:
                    try:
                        tool_result = await self.tools.execute(pending)
                    except ToolExecutionError as exc:
                        errors.append(f"tool execution failed: {exc}")
                        tool_result = {"ok": False, "error": str(exc)}
                response_text = _response_from_tool(tool_result) or pending.response_text or "Confirmed and executed."
                self.memory.add_turn("user", cleaned)
                self.memory.add_turn("assistant", response_text, tool=pending.tool_name)
                return await self._finish(
                    cleaned=cleaned,
                    intent=pending,
                    permission=permission,
                    tool_result=tool_result,
                    response_text=response_text,
                    speak=speak,
                    play_local=play_local,
                    require_wake_word=require_wake_word,
                    wake_triggered=wake_triggered,
                    errors=tuple(errors),
                )
            if is_cancel_phrase(cleaned):
                self._pending_intent = None
                self.memory.add_turn("user", cleaned)
                self.memory.add_turn("assistant", "Cancelled.")
                return await self._finish(
                    cleaned=cleaned,
                    intent=noop_intent(cleaned, "Cancelled."),
                    permission=PermissionDecision(True, False, False, "cancelled by user"),
                    tool_result=None,
                    response_text="Cancelled.",
                    speak=speak,
                    play_local=play_local,
                    require_wake_word=require_wake_word,
                    wake_triggered=wake_triggered,
                    errors=tuple(errors),
                )

        # 4) Local LLM + memory context (with deterministic offline fallback if Ollama isn't running)
        context = self.memory.context_summary(limit=6)
        try:
            intent = await detect_intent(self.llm, cleaned, wake_name=wake_name, context=context)
        except LocalLLMUnavailable as exc:
            errors.append(f"local LLM unavailable (using offline rule parser): {exc}")
            intent = offline_fallback_intent(cleaned, wake_name=wake_name)

        # 5) Permission layer & multi-step LLM loop (max 4 steps)
        tool_result: dict[str, Any] | None = None
        permission = self.permissions.check(intent, approval=approval)
        if permission.needs_approval and intent.tool is not None:
            self._pending_intent = intent
            prompt = f"Approval required for {permission.reason}. Say 'Yes, go ahead' to confirm or 'Cancel' to abort."
            return await self._finish(
                cleaned=cleaned,
                intent=intent,
                permission=permission,
                tool_result=None,
                response_text=prompt,
                speak=speak,
                play_local=play_local,
                require_wake_word=require_wake_word,
                wake_triggered=wake_triggered,
                errors=tuple(errors),
            )

        if intent.tool is not None and permission.allowed:
            try:
                tool_result = await self.tools.execute(intent)
            except ToolExecutionError as exc:
                errors.append(f"tool execution failed: {exc}")
                tool_result = {"ok": False, "error": str(exc)}

            if self.llm is not None and intent.raw.get("done") is False:
                messages = [
                    {"role": "system", "content": INTENT_SYSTEM},
                    {"role": "user", "content": cleaned},
                ]
                for _ in range(3):
                    messages.append({"role": "assistant", "content": json.dumps(intent.raw, ensure_ascii=False)})
                    messages.append({"role": "user", "content": f"Tool observation: {json.dumps(tool_result, ensure_ascii=False)[:2000]}"})
                    try:
                        next_data = await self.llm.chat_messages(messages)
                    except LocalLLMUnavailable:
                        break
                    next_intent = _coerce_intent(next_data, cleaned)
                    next_perm = self.permissions.check(next_intent, approval=approval)
                    if next_perm.needs_approval and next_intent.tool is not None:
                        self._pending_intent = next_intent
                        prompt = f"Approval required for {next_perm.reason}. Say 'Yes, go ahead' to confirm or 'Cancel' to abort."
                        return await self._finish(
                            cleaned=cleaned,
                            intent=next_intent,
                            permission=next_perm,
                            tool_result=tool_result,
                            response_text=prompt,
                            speak=speak,
                            play_local=play_local,
                            require_wake_word=require_wake_word,
                            wake_triggered=wake_triggered,
                            errors=tuple(errors),
                        )
                    intent, permission = next_intent, next_perm
                    if intent.tool is None or not permission.allowed:
                        break
                    try:
                        tool_result = await self.tools.execute(intent)
                    except ToolExecutionError as exc:
                        errors.append(f"tool execution failed: {exc}")
                        tool_result = {"ok": False, "error": str(exc)}
                        break
                    if intent.raw.get("done") is not False:
                        break

        response_text = intent.response_text or _response_from_tool(tool_result) or cleaned
        self.memory.add_turn("user", cleaned)
        self.memory.add_turn("assistant", response_text, tool=intent.tool_name)
        return await self._finish(
            cleaned=cleaned,
            intent=intent,
            permission=permission,
            tool_result=tool_result,
            response_text=response_text,
            speak=speak,
            play_local=play_local,
            require_wake_word=require_wake_word,
            wake_triggered=wake_triggered,
            errors=tuple(errors),
        )

    async def _finish(
        self,
        *,
        cleaned: str,
        intent: Intent,
        permission: PermissionDecision,
        tool_result: dict[str, Any] | None,
        response_text: str,
        speak: bool,
        play_local: bool,
        require_wake_word: bool,
        wake_triggered: bool,
        errors: tuple[str, ...],
    ) -> PekkaPipelineResult:
        spoken: PiperSpeechResult | None = None
        if speak and response_text:
            spoken = await self.tts.speak(response_text, play_local=play_local)
        return PekkaPipelineResult(
            transcript=cleaned,
            intent=intent,
            permission=permission,
            tool_result=tool_result,
            response_text=response_text,
            spoken=spoken,
            require_wake_word=require_wake_word,
            wake_triggered=wake_triggered,
            errors=errors,
        )


def _response_from_tool(tool_result: dict[str, Any] | None) -> str:
    if not tool_result:
        return ""
    if tool_result.get("ok") is False:
        return f"I couldn't do that: {tool_result.get('error', 'tool failed')}"
    result = tool_result.get("result")
    if isinstance(result, dict) and result.get("message"):
        return str(result["message"])
    return ""
