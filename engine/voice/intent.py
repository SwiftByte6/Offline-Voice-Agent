"""Intent detection for P.E.K.K.A using a local LLM (with offline rule fallback)."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any

from engine.speech.transcript import clean_transcript
from .local_llm import LocalLLM

TOOL_NAMES = ("pekka_act", "pekka_ocr", "pekka_screen", "pekka_run_task")

INTENT_SYSTEM = """You are P.E.K.K.A intent detection. Return ONLY a JSON object, no prose.

Schema:
{
  "intent": "chat" | "tool" | "noop" | "blocked" | "needs_approval",
  "tool": null | {"name": "pekka_act" | "pekka_ocr" | "pekka_screen" | "pekka_run_task", "args": {}},
  "response_text": "short spoken reply",
  "requires_approval": false,
  "reason": "short reason",
  "done": true
}

Rules:
- The user transcript is speech-to-text; ignore wake name "Hey P.E.K.K.A" / "P.E.K.K.A".
- For pure conversation use intent="chat", tool=null.
- For desktop actions use intent="tool" with tool.name="pekka_act".
  pekka_act args: {"action":"click"|"double_click"|"right_click"|"click_text"|"type"|"type_into"|"hotkey"|"scroll"|"move"|"mouse_drag"|"list_windows"|"window_control"|"find_controls"|"read_window"|"open_folder"|"select_files"|"wait_for_window", ...}
  click/type/hotkey/mouse_drag require permission; read/list/move/scroll/open_folder/select_files are lower risk.
- Never pay, send, buy, delete, confirm, submit, restart, shutdown. intent="blocked".
- If action needs user confirmation, intent="needs_approval", requires_approval=true.
- For multi-step tasks where you need tool output before the next step, set "done": false.
- Keep response_text short.
"""


@dataclass(frozen=True)
class Intent:
    intent: str = "noop"
    tool: dict[str, Any] | None = None
    response_text: str = ""
    requires_approval: bool = False
    reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def tool_name(self) -> str | None:
        if isinstance(self.tool, dict):
            return self.tool.get("name")
        return None

    @property
    def tool_args(self) -> dict[str, Any]:
        if isinstance(self.tool, dict) and isinstance(self.tool.get("args"), dict):
            return self.tool["args"]
        return {}


def _coerce_intent(data: dict[str, Any], transcript: str) -> Intent:
    intent = str(data.get("intent") or "noop")
    tool = data.get("tool")
    if tool is not None and not isinstance(tool, dict):
        tool = None
    if tool is not None:
        name = tool.get("name")
        if name not in TOOL_NAMES:
            tool = None
            intent = "noop"
        args = tool.get("args", {}) if tool else {}
        if not isinstance(args, dict):
            args = {}
        tool = {"name": name, "args": args} if tool else None
    response = str(data.get("response_text") or "").strip()
    return Intent(
        intent=intent,
        tool=tool,
        response_text=response,
        requires_approval=bool(data.get("requires_approval", intent == "needs_approval")),
        reason=str(data.get("reason") or ""),
        raw=data,
    )


def noop_intent(transcript: str, response_text: str | None = None) -> Intent:
    return Intent(intent="chat", tool=None, response_text=response_text if response_text is not None else transcript, raw={})


_APPROVAL_RE = re.compile(r"^(yes,?\s*)?(go ahead|confirm|approved?|do it|proceed|yes please|yes)\b", re.I)
_CANCEL_RE = re.compile(r"^(no|cancel|abort|stop|never\s*mind|don'?t)\b", re.I)


def is_approval_phrase(text: str) -> bool:
    return bool(_APPROVAL_RE.match((text or "").strip()))


def is_cancel_phrase(text: str) -> bool:
    return bool(_CANCEL_RE.match((text or "").strip()))


def offline_fallback_intent(transcript: str, *, wake_name: str = "P.E.K.K.A") -> Intent:
    """Deterministic offline intent parser when no local LLM is running yet."""
    cleaned = clean_transcript(transcript, strip_name=True, wake_name=wake_name)
    if not cleaned:
        return Intent(intent="noop", response_text="", raw={})
    low = cleaned.lower().strip()

    if re.search(r"\b(delete|wipe|format|shutdown|restart|pay|purchase|buy)\b", low):
        return Intent(
            intent="blocked",
            tool=None,
            response_text="That action is blocked for safety.",
            requires_approval=False,
            reason="blocked action keyword",
            raw={"source": "offline_rule"},
        )

    if any(sep in low for sep in (" and then ", " then ", ",")) or ("copy" in low and "paste" in low):
        return Intent(
            intent="needs_approval",
            tool={"name": "pekka_run_task", "args": {"task": "multi_step", "params": {"command": cleaned}}},
            response_text="Running multi-step task.",
            requires_approval=True,
            reason="multi-step desktop automation",
            raw={"source": "offline_rule", "command": cleaned},
        )

    if re.search(r"\b(list|show|what)\b.*\bwindows?\b", low):
        return Intent(
            intent="tool",
            tool={"name": "pekka_act", "args": {"action": "list_windows"}},
            response_text="Listing open windows.",
            requires_approval=False,
            reason="list open windows",
            raw={"source": "offline_rule"},
        )

    m_win = re.match(r"^(focus|switch to|minimize|minimise|maximize|maximise|restore|close)\s+(.+)$", low)
    if m_win:
        verb, target = m_win.group(1), m_win.group(2).strip()
        act_map = {"switch to": "focus", "minimise": "minimize", "maximise": "maximize"}
        win_act = act_map.get(verb, verb)
        return Intent(
            intent="needs_approval" if win_act == "close" else "tool",
            tool={"name": "pekka_act", "args": {"action": "window_control", "window": target, "window_action": win_act}},
            response_text=f"{win_act.capitalize()} {target}.",
            requires_approval=(win_act == "close"),
            reason=f"window {win_act}",
            raw={"source": "offline_rule"},
        )

    m_folder = re.match(r"^open\s+(?:my\s+)?(.+?)\s+folder$", low)
    if m_folder:
        folder = m_folder.group(1).strip()
        return Intent(
            intent="tool",
            tool={"name": "pekka_act", "args": {"action": "open_folder", "name": folder}},
            response_text=f"Opening {folder} folder.",
            requires_approval=False,
            reason="open folder",
            raw={"source": "offline_rule"},
        )

    if re.search(r"\b(read|what'?s on|what is on|scan)\b.*\bscreen\b|\bocr\b", low):
        return Intent(
            intent="tool",
            tool={"name": "pekka_ocr", "args": {}},
            response_text="Reading the screen.",
            requires_approval=False,
            reason="read screen via OCR",
            raw={"source": "offline_rule"},
        )

    if re.search(r"\b(screenshot|capture screen|take a screen)\b", low):
        return Intent(
            intent="tool",
            tool={"name": "pekka_screen", "args": {}},
            response_text="Captured the screen.",
            requires_approval=False,
            reason="capture screen",
            raw={"source": "offline_rule"},
        )

    m_click = re.match(r"^(double click|right click|click)\s+(?:on\s+)?(.+)$", low)
    if m_click:
        kind_raw = m_click.group(1)
        target = cleaned[m_click.start(2) :].strip()
        return Intent(
            intent="needs_approval",
            tool={
                "name": "pekka_act",
                "args": {
                    "action": "double_click" if kind_raw == "double click" else ("right_click" if kind_raw == "right click" else "click"),
                    "text": target,
                },
            },
            response_text=f"Clicking {target}.",
            requires_approval=True,
            reason="click UI element",
            raw={"source": "offline_rule"},
        )

    m_type = re.match(r"^type\s+(.+)$", cleaned, re.I)
    if m_type:
        return Intent(
            intent="needs_approval",
            tool={"name": "pekka_act", "args": {"action": "type", "text": m_type.group(1).strip()}},
            response_text="Typing text.",
            requires_approval=True,
            reason="type text",
            raw={"source": "offline_rule"},
        )

    return noop_intent(cleaned, cleaned)


async def detect_intent(
    llm: LocalLLM | None,
    transcript: str,
    *,
    wake_name: str = "P.E.K.K.A",
    context: str = "",
) -> Intent:
    """Use local LLM; if no LLM, return offline rule-based intent. Raises LocalLLMUnavailable if LLM fails."""
    transcript = clean_transcript(transcript, strip_name=True, wake_name=wake_name)
    if not transcript:
        return Intent(intent="noop", response_text="", raw={})
    if llm is None:
        return offline_fallback_intent(transcript, wake_name=wake_name)
    payload: dict[str, Any] = {"transcript": transcript, "wake_name": wake_name}
    if context:
        payload["memory_context"] = context
    user = json.dumps(payload, ensure_ascii=False)
    data = await llm.chat_json(INTENT_SYSTEM, user)
    return _coerce_intent(data, transcript)
