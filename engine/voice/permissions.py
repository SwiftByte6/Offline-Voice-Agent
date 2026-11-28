"""Permission layer for P.E.K.K.A tool execution."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .intent import Intent

BLOCKED_ACTIONS = {
    "pay", "purchase", "buy", "send", "submit", "confirm", "delete", "delete_path",
    "post", "post_message", "shutdown", "restart", "format", "wipe", "run_command",
}
ALWAYS_ASK = {"click", "double_click", "right_click", "type", "hotkey"}
LOW_RISK = {"move", "scroll"}
READ_ONLY_TOOLS = {"pekka_ocr", "pekka_screen"}
BLOCKED_WORDS = (
    "pay", "payment", "purchase", "buy", "checkout", "order", "send", "submit",
    "confirm", "delete", "remove", "shutdown", "restart", "format", "wipe",
    "password", "credit card", "cvc", "cvv", "otp", "upi",
)


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    needs_approval: bool
    blocked: bool
    reason: str

    @property
    def needs_user_approval(self) -> bool:
        return self.needs_approval


def _contains_blocked_word(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in BLOCKED_WORDS)


class PermissionLayer:
    def __init__(self, approval: bool = False) -> None:
        self.approval = approval

    def check(self, intent: Intent, *, approval: bool | None = None) -> PermissionDecision:
        approved = self.approval if approval is None else approval
        if intent.intent == "blocked":
            return PermissionDecision(False, False, True, intent.reason or "blocked intent")
        if intent.intent == "needs_approval" or intent.requires_approval:
            if not approved:
                return PermissionDecision(False, True, False, "needs user approval")
        tool = intent.tool_name
        if tool is None:
            return PermissionDecision(True, False, False, "no tool")
        if tool in READ_ONLY_TOOLS:
            return PermissionDecision(True, False, False, "read-only tool")
        if tool not in {"pekka_act", "pekka_run_task", *READ_ONLY_TOOLS}:
            return PermissionDecision(False, False, True, f"unknown tool {tool}")
        args = intent.tool_args
        action = str(args.get("action") or "").lower()
        if action in BLOCKED_ACTIONS or _contains_blocked_word(json_safe(args)):
            return PermissionDecision(False, False, True, "dangerous action blocked")
        if tool == "pekka_act":
            if action in LOW_RISK:
                return PermissionDecision(True, False, False, "low risk")
            if action in ALWAYS_ASK:
                if approved:
                    return PermissionDecision(True, False, False, "approved")
                return PermissionDecision(False, True, False, f"{action or 'action'} needs approval")
            return PermissionDecision(True, False, False, "approved") if approved else PermissionDecision(False, True, False, "unknown action needs approval")
        if tool == "pekka_run_task":
            if approved:
                return PermissionDecision(True, False, False, "approved")
            return PermissionDecision(False, True, False, "task needs approval")
        return PermissionDecision(True, False, False, "approved") if approved else PermissionDecision(False, True, False, "needs approval")


def json_safe(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)
