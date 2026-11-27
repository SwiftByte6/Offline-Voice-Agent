"""Observe, plan, act, and confirm loop for NOVA desktop automation."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import re
import threading
import uuid
from typing import Any

from engine.agent import file_tools
from engine.llm.lfm_service import LFMService
from engine.vision.service import capture_screen_array, execute_action, ocr_to_prompt_text, run_ocr

MAX_ACTIONS_PER_PLAN = 3
MAX_AGENT_CYCLES = 8
UI_ACTIONS = {"click", "double_click", "right_click", "type", "hotkey", "scroll", "move", "open", "navigate_url"}
FILE_ACTIONS = {"search_files", "rename_file", "move_file", "copy_file", "delete_file", "open_file", "open_url"}
SUPPORTED_ACTIONS = UI_ACTIONS | FILE_ACTIONS | {"close_app", "send", "publish"}
CONFIRMATION_ACTIONS = {"delete_file", "close_app", "publish", "send"}

logger = logging.getLogger("nova.agent")

SYSTEM_PROMPT = """You are NOVA, a local Windows desktop automation planner.
Work in a loop. Read the latest screen OCR and completed action results, then return at most three next actions.
Return only JSON: {"summary":"short description","complete":false,"actions":[{"action":"click","x":0,"y":0}]}
Supported UI actions: click, double_click, right_click, move, type, hotkey, scroll, open, navigate_url, close_app, send, publish.
Supported file actions: search_files, rename_file, move_file, copy_file, delete_file, open_file, open_url.
search_files requires query and location (Desktop, Downloads, Documents, or Pictures). It returns full file paths in action results.
rename_file requires source and new_name. move_file and copy_file require source and destination_dir. delete_file and open_file require source. open_url and navigate_url require url.
Use OCR coordinates only for visible targets. send and publish require x and y coordinates for their visible button. Use open for a Windows Start-menu search target.
Use open only for a Windows application or folder. Use navigate_url after opening a browser when the user wants a website in a particular browser. Use open_url only when the user explicitly supplied an http or https URL and did not specify a browser. For "open Chrome", "open Camera", or "open File Explorer", use open with target set to the app name.
Never invent a file path. After search_files, use a returned full path. Set complete=true only when the user goal is complete.
Deletion, closing apps, overwriting a destination, sending, and publishing require user confirmation; still include the requested action so NOVA can pause for confirmation."""


class PlanValidationError(ValueError):
    """Raised when LFM3 does not return a supported action plan."""


@dataclass
class AgentSession:
    instruction: str
    history: list[dict[str, Any]] = field(default_factory=list)
    cycle: int = 0
    pending_action: dict[str, Any] | None = None


class DesktopAgent:
    """Runs short plans, refreshes OCR context, and persists confirmation pauses."""

    def __init__(self, lfm_service: LFMService) -> None:
        self._lfm_service = lfm_service
        self._sessions: dict[str, AgentSession] = {}
        self._sessions_lock = threading.Lock()

    def run(self, instruction: str, execute: bool = True) -> dict[str, Any]:
        session = AgentSession(instruction=instruction)
        browser_navigation = self._browser_navigation(instruction)
        if browser_navigation:
            browser, url = browser_navigation
            plan = {
                "summary": f"Open {url} in {browser}",
                "complete": True,
                "actions": [
                    {"action": "open", "target": browser},
                    {"action": "navigate_url", "url": url},
                ],
            }
            if not execute:
                return {"success": True, "executed": False, **plan, "results": []}
            results = []
            for action in plan["actions"]:
                result = self._execute(action)
                results.append({"action": action, **result})
                if not result["success"]:
                    return {"success": False, "executed": True, **plan, "results": results}
            return {"success": True, "executed": True, **plan, "results": results}

        direct_target = self._simple_open_target(instruction)
        if direct_target:
            plan = {"summary": f"Open {direct_target}", "complete": True, "actions": [{"action": "open", "target": direct_target}]}
            if not execute:
                return {"success": True, "executed": False, **plan, "results": []}
            result = self._execute(plan["actions"][0])
            return {"success": result["success"], "executed": True, **plan, "results": [{"action": plan["actions"][0], **result}]}

        # A few common Windows launch requests have an unambiguous first step.
        # Performing it directly keeps app launches reliable even if the small local
        # planner emits a malformed coordinate-only action for the first cycle.
        leading_target = self._leading_open_target(instruction)
        if leading_target:
            leading_action = {"action": "open", "target": leading_target}
            if execute:
                result = self._execute(leading_action)
                session.history.append({"action": leading_action, **result})
                if not result["success"]:
                    return {
                        "success": False,
                        "executed": True,
                        "summary": f"Could not open {leading_target}",
                        "actions": [leading_action],
                        "results": session.history,
                    }
            else:
                session.history.append({"action": leading_action, "success": True, "message": "planned"})
        return self._advance(session, execute=execute)

    def confirm(self, confirmation_id: str, approved: bool) -> dict[str, Any]:
        with self._sessions_lock:
            session = self._sessions.pop(confirmation_id, None)
        if session is None or session.pending_action is None:
            raise PlanValidationError("This confirmation request has expired.")
        if not approved:
            return {
                "success": True,
                "executed": False,
                "confirmation_rejected": True,
                "summary": "Confirmation rejected; no protected action was performed.",
                "results": session.history,
            }

        result = self._execute(session.pending_action, confirmed=True)
        session.history.append({"action": session.pending_action, **result})
        return self._advance(session, execute=True)

    def _advance(self, session: AgentSession, execute: bool) -> dict[str, Any]:
        latest_plan: dict[str, Any] | None = None
        while session.cycle < MAX_AGENT_CYCLES:
            session.cycle += 1
            latest_plan = self._plan_next(session)
            if not execute:
                return {"success": True, "executed": False, **latest_plan, "results": session.history}
            if latest_plan["complete"] or not latest_plan["actions"]:
                return {
                    "success": True,
                    "executed": True,
                    **latest_plan,
                    "results": session.history,
                }

            for action in latest_plan["actions"]:
                confirmation = self._confirmation_message(action)
                if confirmation:
                    confirmation_id = uuid.uuid4().hex
                    session.pending_action = action
                    with self._sessions_lock:
                        self._sessions[confirmation_id] = session
                    logger.info("Agent awaiting confirmation for: %s", json.dumps(action, ensure_ascii=False))
                    return {
                        "success": True,
                        "executed": True,
                        "confirmation_required": True,
                        "confirmation_id": confirmation_id,
                        "confirmation_message": confirmation,
                        "pending_action": action,
                        **latest_plan,
                        "results": session.history,
                    }

                result = self._execute(action)
                if result.get("requires_confirmation"):
                    confirmation_id = uuid.uuid4().hex
                    session.pending_action = action
                    with self._sessions_lock:
                        self._sessions[confirmation_id] = session
                    return {
                        "success": True,
                        "executed": True,
                        "confirmation_required": True,
                        "confirmation_id": confirmation_id,
                        "confirmation_message": f"Overwrite '{result['destination']}'?",
                        "pending_action": action,
                        **latest_plan,
                        "results": session.history,
                    }
                session.history.append({"action": action, **result})
                if not result["success"]:
                    return {"success": False, "executed": True, **latest_plan, "results": session.history}

        return {
            "success": False,
            "executed": True,
            "summary": "Stopped after the maximum planning cycles.",
            "actions": latest_plan["actions"] if latest_plan else [],
            "results": session.history,
        }

    def _plan_next(self, session: AgentSession) -> dict[str, Any]:
        screen, width, height = capture_screen_array()
        ocr_items = run_ocr(screen)
        prompt = self._build_user_prompt(session, width, height, ocr_items)
        logger.info("Agent input transcript: %s", session.instruction)
        logger.info("Agent OCR items: %s", json.dumps(ocr_items, ensure_ascii=False))
        logger.info("Agent LLM user prompt:\n%s", prompt)
        raw_plan = self._lfm_service.create_plan(SYSTEM_PROMPT, prompt)
        logger.info("Agent raw LLM output:\n%s", raw_plan)
        plan = self._parse_plan(raw_plan, session.instruction)
        logger.info("Agent validated plan: %s", json.dumps(plan, ensure_ascii=False))
        return {**plan, "screen": {"width": width, "height": height}, "ocr_items": ocr_items}

    def _execute(self, action: dict[str, Any], confirmed: bool = False) -> dict[str, Any]:
        logger.info("Agent executing action: %s", json.dumps(action, ensure_ascii=False))
        try:
            if action["action"] in UI_ACTIONS:
                result = execute_action(action)
            elif action["action"] in {"send", "publish"}:
                result = execute_action({"action": "click", "x": action["x"], "y": action["y"]})
            elif action["action"] == "close_app":
                result = execute_action({"action": "hotkey", "keys": ["alt", "f4"]})
            elif action["action"] == "search_files":
                result = file_tools.search_files(action["query"], action["location"])
            elif action["action"] == "rename_file":
                result = file_tools.rename_file(action["source"], action["new_name"], overwrite=confirmed)
            elif action["action"] == "move_file":
                result = file_tools.move_file(action["source"], action["destination_dir"], overwrite=confirmed)
            elif action["action"] == "copy_file":
                result = file_tools.copy_file(action["source"], action["destination_dir"], overwrite=confirmed)
            elif action["action"] == "delete_file":
                result = file_tools.delete_file(action["source"])
            elif action["action"] == "open_file":
                result = file_tools.open_file(action["source"])
            elif action["action"] == "open_url":
                result = file_tools.open_url(action["url"])
            else:
                result = {"success": False, "message": f"unknown action '{action['action']}'"}
        except (file_tools.FileToolError, OSError) as exc:
            result = {"success": False, "message": str(exc)}
        logger.info("Agent action result: %s", json.dumps(result, ensure_ascii=False))
        return result

    @staticmethod
    def _confirmation_message(action: dict[str, Any]) -> str | None:
        kind = action["action"]
        if kind == "delete_file":
            return f"Delete '{action['source']}'?"
        if kind == "close_app":
            return "Close the active application? Unsaved work may be lost."
        if kind in {"rename_file", "move_file", "copy_file"}:
            return None
        if kind in CONFIRMATION_ACTIONS:
            return f"Approve protected action '{kind}'?"
        return None

    @staticmethod
    def _build_user_prompt(session: AgentSession, width: int, height: int, ocr_items: list[dict[str, Any]]) -> str:
        ocr_text = ocr_to_prompt_text(ocr_items[:100]) or "(No readable text detected.)"
        history = json.dumps(session.history[-8:], ensure_ascii=False) if session.history else "[]"
        return (
            f"User instruction: {session.instruction.strip()}\n"
            f"Planning cycle: {session.cycle} of {MAX_AGENT_CYCLES}\n"
            f"Completed action results: {history}\n\n"
            f"Screen dimensions: {width}x{height}\n"
            f"OCR text and bounding boxes:\n{ocr_text}"
        )

    @staticmethod
    def _parse_plan(raw_plan: str, instruction: str) -> dict[str, Any]:
        candidate = raw_plan.strip()
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
        if fence_match:
            candidate = fence_match.group(1)
        else:
            object_match = re.search(r"\{.*\}", candidate, re.DOTALL)
            if object_match:
                candidate = object_match.group(0)
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise PlanValidationError("LFM3 did not return a valid JSON task plan.") from exc
        raw_actions = payload.get("actions", [])
        if not isinstance(raw_actions, list):
            raise PlanValidationError("LFM3 task plan has an invalid actions list.")
        actions = []
        for raw_action in raw_actions[:MAX_ACTIONS_PER_PLAN]:
            try:
                actions.append(DesktopAgent._validate_action(raw_action, instruction))
            except PlanValidationError as exc:
                logger.warning("Discarded malformed LLM action %s: %s", raw_action, exc)
        if raw_actions and not actions:
            raise PlanValidationError("LFM3 returned actions without the fields required to execute them.")
        return {
            "summary": str(payload.get("summary", ""))[:240],
            "complete": bool(payload.get("complete", False)),
            "actions": actions,
        }

    @staticmethod
    def _validate_action(raw_action: Any, instruction: str = "") -> dict[str, Any]:
        if not isinstance(raw_action, dict):
            raise PlanValidationError("Each task action must be an object.")
        action = str(raw_action.get("action", "")).strip().lower()
        if action not in SUPPORTED_ACTIONS:
            raise PlanValidationError(f"Unsupported task action '{action}'.")
        cleaned: dict[str, Any] = {"action": action}
        if action in {"click", "double_click", "right_click", "move", "send", "publish"}:
            if "x" not in raw_action or "y" not in raw_action:
                raise PlanValidationError(f"{action} requires x and y coordinates.")
            cleaned.update(x=int(raw_action["x"]), y=int(raw_action["y"]))
        elif action == "type":
            cleaned["text"] = str(raw_action.get("text", ""))[:2000]
        elif action == "open":
            target = str(raw_action.get("target", "")).strip()[:200]
            if not target:
                target = DesktopAgent._simple_open_target(instruction) or ""
            if not target:
                raise PlanValidationError("open requires target.")
            cleaned["target"] = target
        elif action == "hotkey":
            keys = raw_action.get("keys", [])
            cleaned["keys"] = [str(key).lower() for key in (keys if isinstance(keys, list) else [keys])][:5]
        elif action == "scroll":
            cleaned["amount"] = max(-20, min(20, int(raw_action.get("amount", 0))))
        elif action == "search_files":
            cleaned["query"] = DesktopAgent._required_string(raw_action, "query", 200)
            cleaned["location"] = str(raw_action.get("location", "Downloads"))
        elif action == "rename_file":
            cleaned["source"] = DesktopAgent._required_string(raw_action, "source", 600)
            cleaned["new_name"] = DesktopAgent._required_string(raw_action, "new_name", 200)
        elif action in {"move_file", "copy_file"}:
            cleaned["source"] = DesktopAgent._required_string(raw_action, "source", 600)
            cleaned["destination_dir"] = DesktopAgent._required_string(raw_action, "destination_dir", 600)
        elif action in {"delete_file", "open_file"}:
            cleaned["source"] = DesktopAgent._required_string(raw_action, "source", 600)
        elif action == "open_url":
            cleaned["url"] = DesktopAgent._required_string(raw_action, "url", 2_000)
        elif action == "navigate_url":
            cleaned["url"] = DesktopAgent._required_string(raw_action, "url", 2_000)
        return cleaned

    @staticmethod
    def _required_string(payload: dict[str, Any], field_name: str, limit: int) -> str:
        value = str(payload.get(field_name, "")).strip()[:limit]
        if not value:
            raise PlanValidationError(f"{payload.get('action')} requires {field_name}.")
        return value

    @staticmethod
    def _simple_open_target(instruction: str) -> str | None:
        clean = instruction.strip().rstrip(".?!")
        match = re.match(r"^(?:please\s+)?(?:open|launch|start)\s+(.+)$", clean, re.IGNORECASE)
        if not match:
            return None
        target = match.group(1).strip()
        if re.search(r"\b(and|then|after|folder|download|downloads)\b", target, re.IGNORECASE):
            return None
        if re.search(r"\b(?:in|on|using|with)\s+(?:google\s+)?chrome\b", target, re.IGNORECASE):
            return None
        return target[:100] or None

    @staticmethod
    def _browser_navigation(instruction: str) -> tuple[str, str] | None:
        """Parse a clear 'open site in Chrome' request without treating it as an app name."""
        clean = instruction.strip().rstrip(".?!")
        match = re.match(
            r"^(?:please\s+)?(?:open|visit|go to|navigate to)\s+(.+?)\s+(?:in|on|using|with)\s+(google\s+)?chrome$",
            clean,
            re.IGNORECASE,
        )
        if not match:
            return None
        destination = match.group(1).strip().casefold()
        aliases = {
            "youtube": "https://www.youtube.com",
            "youtube.com": "https://www.youtube.com",
            "google": "https://www.google.com",
            "google.com": "https://www.google.com",
        }
        if destination in aliases:
            return "Google Chrome", aliases[destination]
        if re.fullmatch(r"(?:https?://)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/[^\s]*)?", destination):
            return "Google Chrome", destination if destination.startswith("http") else f"https://{destination}"
        return None

    @staticmethod
    def _leading_open_target(instruction: str) -> str | None:
        """Recognize an unambiguous Windows app/folder launch at the start of a longer request."""
        clean = instruction.strip().rstrip(".?!")
        match = re.match(r"^(?:please\s+)?(?:open|launch|start)\s+(.+)$", clean, re.IGNORECASE)
        if not match:
            return None
        requested = match.group(1).strip()
        normalized = re.sub(r"\s+", " ", requested).casefold()
        if re.match(r"^(?:file explorer|explorer)\b", normalized):
            # Starting a Downloads request directly opens Explorer at the right folder.
            if re.search(r"\bdownloads?\b", normalized):
                return "Downloads"
            return "File Explorer"
        for app_name in ("google chrome", "chrome", "camera"):
            if re.match(rf"^{re.escape(app_name)}\b", normalized):
                return app_name.title() if app_name != "google chrome" else "Google Chrome"
        return None
