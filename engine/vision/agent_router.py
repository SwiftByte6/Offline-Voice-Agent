"""Hybrid voice command parser and UIA -> RapidOCR -> template grounding router."""

from __future__ import annotations

from difflib import SequenceMatcher
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any
import winreg

import pyautogui

from engine.config import GeminiConfig
from engine.vision.gemini_planner import run_gemini_agent
from engine.vision.service import (
    capture_screen_array,
    execute_action,
    ocr_to_prompt_text,
    run_ocr,
)
from engine.vision.uia_service import (
    _boxes_overlap,
    collect_uia_elements,
    get_nova_window_boxes,
)

logger = logging.getLogger("nova.agent_router")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

STOP_WORDS = {"the", "a", "an", "my", "this", "that"}

BUILTIN_APP_ALIASES: dict[str, str] = {
    "settings": "ms-settings:",
    "windows settings": "ms-settings:",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "notepad": "notepad.exe",
    "paint": "mspaint.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
}

HOTKEY_ALIASES: dict[str, list[str]] = {
    "copy": ["ctrl", "c"],
    "paste": ["ctrl", "v"],
    "cut": ["ctrl", "x"],
    "undo": ["ctrl", "z"],
    "redo": ["ctrl", "y"],
    "select all": ["ctrl", "a"],
    "save": ["ctrl", "s"],
    "find": ["ctrl", "f"],
    "new tab": ["ctrl", "t"],
    "close tab": ["ctrl", "w"],
    "close window": ["alt", "f4"],
    "switch window": ["alt", "tab"],
    "alt tab": ["alt", "tab"],
    "enter": ["enter"],
    "return": ["enter"],
    "escape": ["escape"],
    "esc": ["escape"],
    "tab": ["tab"],
    "space": ["space"],
    "backspace": ["backspace"],
    "delete": ["delete"],
}


def _clean_command_text(raw: str) -> str:
    text = (raw or "").strip()
    return text.rstrip(".!?,;:")


def _clean_target_phrase(raw: str) -> str:
    text = (raw or "").strip().strip("\"'")
    tokens = text.split()
    while len(tokens) > 1 and tokens[0].lower() in STOP_WORDS:
        tokens.pop(0)
    return " ".join(tokens).strip()


def _normalize_label(value: str) -> str:
    lowered = (value or "").lower()
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_voice_intent(command: str) -> dict[str, Any]:
    """Parse a transcribed voice command into a structured action intent."""
    cleaned = _clean_command_text(command)
    if not cleaned:
        return {"action": "none", "raw": command}

    lower = cleaned.lower()

    if re.search(
        r"\b(?:and|then)\b\s+(?:click|tap|open|launch|start|type|write|search|press|scroll|close|add|select|go|find)\b",
        lower,
    ):
        return {"action": "multi_step", "raw": cleaned}

    if re.match(r"^(read|what(?:'s| is) on)( the)? screen$", lower):
        return {"action": "read_screen", "raw": cleaned}

    scroll_match = re.match(r"^scroll\s+(up|down)(?:\s+(?:a\s+)?(?:lot|more|page))?$", lower)
    if scroll_match:
        direction = scroll_match.group(1)
        is_large = any(word in lower for word in ("lot", "more", "page"))
        magnitude = 700 if is_large else 350
        return {
            "action": "scroll",
            "amount": magnitude if direction == "up" else -magnitude,
            "raw": cleaned,
        }

    dbl_match = re.match(r"^double[\s-]+click(?:\s+on)?\s+(.+)$", cleaned, re.IGNORECASE)
    if dbl_match:
        return {
            "action": "double_click",
            "target": _clean_target_phrase(dbl_match.group(1)),
            "raw": cleaned,
        }

    right_match = re.match(r"^right[\s-]+click(?:\s+on)?\s+(.+)$", cleaned, re.IGNORECASE)
    if right_match:
        return {
            "action": "right_click",
            "target": _clean_target_phrase(right_match.group(1)),
            "raw": cleaned,
        }

    launch_match = re.match(
        r"^(?:open|launch|start)(?:\s+(?:up|the|app|application))*\s+(.+)$",
        cleaned,
        re.IGNORECASE,
    )
    if launch_match:
        return {
            "action": "click",
            "allow_app_launch": True,
            "target": _clean_target_phrase(launch_match.group(1)),
            "raw": cleaned,
        }

    click_match = re.match(
        r"^(?:click|tap|select)(?:\s+on)?\s+(.+)$",
        cleaned,
        re.IGNORECASE,
    )
    if click_match:
        return {
            "action": "click",
            "allow_app_launch": False,
            "target": _clean_target_phrase(click_match.group(1)),
            "raw": cleaned,
        }

    move_match = re.match(
        r"^(?:move(?:\s+mouse|\s+cursor)?\s+to|hover(?:\s+over)?)\s+(.+)$",
        cleaned,
        re.IGNORECASE,
    )
    if move_match:
        return {
            "action": "move",
            "target": _clean_target_phrase(move_match.group(1)),
            "raw": cleaned,
        }

    type_match = re.match(r"^(?:type|write|input)\s+(.+)$", cleaned, re.IGNORECASE)
    if type_match:
        return {"action": "type", "text": type_match.group(1).strip(), "raw": cleaned}

    hotkey_match = re.match(r"^(?:press|hotkey)\s+(.+)$", cleaned, re.IGNORECASE)
    if hotkey_match:
        raw_keys = hotkey_match.group(1).strip().lower()
        if raw_keys in HOTKEY_ALIASES:
            keys = HOTKEY_ALIASES[raw_keys]
        else:
            normalized_keys = raw_keys.replace("control", "ctrl").replace("plus", "+")
            parts = [p.strip() for p in re.split(r"[+\s]+", normalized_keys) if p.strip()]
            keys = parts
        return {"action": "hotkey", "keys": keys, "raw": cleaned}

    return {"action": "none", "text": cleaned, "raw": cleaned}


def _score_candidate(query: str, candidate: str) -> float:
    q = _normalize_label(query)
    c = _normalize_label(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0

    q_tokens = q.split()
    c_tokens = c.split()
    has_word_match = bool(
        re.search(rf"(?:^|\s){re.escape(q)}(?:\s|$)", c)
        or re.search(rf"(?:^|\s){re.escape(c)}(?:\s|$)", q)
    )
    if has_word_match:
        ratio = min(len(q), len(c)) / max(len(q), len(c))
        if c.startswith(q) or q.startswith(c):
            return 0.84 + 0.12 * ratio
        return 0.78 + 0.14 * ratio

    if q_tokens and all(tok in c_tokens for tok in q_tokens):
        return 0.85

    return SequenceMatcher(None, q, c).ratio() * 0.75


def _best_match(
    target: str,
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, float]:
    best_item: dict[str, Any] | None = None
    best_score = 0.0
    for item in candidates:
        score = _score_candidate(target, item.get("text", ""))
        if score > best_score:
            best_score = score
            best_item = item
    return best_item, best_score


def _match_saved_template(target: str) -> dict[str, Any] | None:
    if not TEMPLATES_DIR.is_dir():
        return None
    slug = _normalize_label(target).replace(" ", "_")
    if not slug:
        return None
    template_path = TEMPLATES_DIR / f"{slug}.png"
    if not template_path.is_file():
        return None
    try:
        point = pyautogui.locateCenterOnScreen(
            str(template_path),
            confidence=0.8,
            grayscale=True,
        )
    except Exception:  # noqa: BLE001
        logger.debug("Template match failed for %s", template_path, exc_info=True)
        return None
    if point is None:
        return None
    return {
        "text": target,
        "box": [int(point.x), int(point.y), int(point.x), int(point.y)],
        "center": [int(point.x), int(point.y)],
        "source": "template",
    }


def resolve_target(
    target: str,
    *,
    allow_ocr: bool = True,
) -> tuple[dict[str, Any] | None, str | None, tuple[int, int] | None]:
    """Resolve a UI target via UIA -> optional RapidOCR -> optional template fallback."""
    excluded_boxes = get_nova_window_boxes()

    uia_items = collect_uia_elements()
    uia_match, uia_score = _best_match(target, uia_items)
    if uia_match is not None and uia_score >= 0.75:
        return uia_match, "uia", None

    ocr_match: dict[str, Any] | None = None
    ocr_score = 0.0
    img_w = 0
    img_h = 0

    if allow_ocr:
        ocr_items: list[dict[str, Any]] = []
        try:
            screen_rgb, img_w, img_h = capture_screen_array()
            ocr_items = [
                item
                for item in run_ocr(screen_rgb)
                if not any(_boxes_overlap(item["box"], ex) for ex in excluded_boxes)
            ]
        except Exception:  # noqa: BLE001
            logger.debug("OCR screen capture failed during target resolution.", exc_info=True)

        ocr_match, ocr_score = _best_match(target, ocr_items)
        if ocr_match is not None and ocr_score >= 0.68:
            return ocr_match, "ocr", (img_w, img_h)

    if uia_match is not None and uia_score >= 0.60 and uia_score >= ocr_score:
        return uia_match, "uia", None
    if allow_ocr and ocr_match is not None and ocr_score >= 0.60:
        return ocr_match, "ocr", (img_w, img_h)

    template_match = _match_saved_template(target)
    if template_match is not None:
        return template_match, "template", None

    return None, None, None


def _find_registry_app_path(exe_name: str) -> str | None:
    subkey = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, None)
                if value and Path(value).exists():
                    return str(value)
        except OSError:
            continue
    return None


def _find_start_menu_shortcut(target: str) -> Path | None:
    q = _normalize_label(target)
    if not q:
        return None
    dirs = [
        Path(os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs")),
        Path(os.path.expandvars(r"%AppData%\Microsoft\Windows\Start Menu\Programs")),
    ]
    best_path: Path | None = None
    best_score = 0.0
    for base_dir in dirs:
        if not base_dir.is_dir():
            continue
        for lnk in base_dir.rglob("*.lnk"):
            score = _score_candidate(q, lnk.stem)
            if score > best_score:
                best_score = score
                best_path = lnk
    return best_path if best_score >= 0.72 else None


def _resolve_app_launch_target(target: str) -> tuple[str, str] | None:
    """Resolve an installed Windows application shortcut, executable, or URI."""
    norm = _normalize_label(target)
    if not norm:
        return None

    shortcut = _find_start_menu_shortcut(norm)
    if shortcut is not None:
        return str(shortcut), shortcut.stem

    alias = BUILTIN_APP_ALIASES.get(norm)
    if alias:
        if alias.endswith(":"):
            return alias, target
        if alias.lower().endswith(".exe"):
            reg_path = _find_registry_app_path(alias)
            if reg_path:
                return reg_path, target
        which_path = shutil.which(alias)
        if which_path:
            return which_path, target
        return alias, target

    exe_candidate = f"{norm.replace(' ', '')}.exe"
    reg_path = _find_registry_app_path(exe_candidate)
    if reg_path:
        return reg_path, target

    which_path = shutil.which(norm)
    if which_path:
        return which_path, target

    return None


def _launch_app(launch_ref: str) -> None:
    if launch_ref.endswith(":"):
        os.startfile(launch_ref)  # noqa: S606
    elif launch_ref.lower().endswith(".lnk"):
        os.startfile(launch_ref)  # noqa: S606
    else:
        subprocess.Popen([launch_ref], close_fds=True)


def route_voice_command(
    command: str,
    execute: bool = True,
    gemini_config: GeminiConfig | None = None,
) -> dict[str, Any]:
    """Parse a spoken command, locate targets via UIA/OCR, or delegate to Gemini multi-step agent."""
    intent = parse_voice_intent(command)
    action = intent["action"]
    has_gemini = bool(gemini_config and gemini_config.api_key)

    if action == "multi_step":
        if has_gemini:
            return run_gemini_agent(
                command,
                gemini_config,
                execute=execute,
                launch_app_fn=_resolve_app_launch_target,
                exec_launch_fn=_launch_app,
            )
        return {
            "success": False,
            "action": "multi_step",
            "executed": False,
            "target": None,
            "matched_by": None,
            "coordinates": None,
            "message": "Multi-step commands require GEMINI_API_KEY in .env.",
        }

    if action == "none":
        if has_gemini:
            return run_gemini_agent(
                command,
                gemini_config,
                execute=execute,
                launch_app_fn=_resolve_app_launch_target,
                exec_launch_fn=_launch_app,
            )
        return {
            "success": True,
            "action": "dictate",
            "executed": False,
            "target": None,
            "matched_by": None,
            "coordinates": None,
            "message": "Dictation only (no desktop command detected).",
        }

    if action == "read_screen":
        if has_gemini and execute:
            return run_gemini_agent(
                command,
                gemini_config,
                execute=True,
                launch_app_fn=_resolve_app_launch_target,
                exec_launch_fn=_launch_app,
            )
        try:
            ocr_items = run_ocr()
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "action": "read_screen",
                "executed": False,
                "target": None,
                "matched_by": None,
                "coordinates": None,
                "message": f"Unable to capture screen for OCR: {exc}",
            }
        summary = ocr_to_prompt_text(ocr_items)
        return {
            "success": True,
            "action": "read_screen",
            "executed": False,
            "target": None,
            "matched_by": "ocr",
            "coordinates": None,
            "message": f"Read {len(ocr_items)} text items from screen.",
            "screen_text": summary,
        }

    if action in {"type", "hotkey", "scroll"}:
        if not execute:
            return {
                "success": True,
                "action": action,
                "executed": False,
                "target": None,
                "matched_by": "intent",
                "coordinates": None,
                "message": f"Dry run: would run {action}.",
            }
        result = execute_action(intent)
        return {
            "success": bool(result.get("success")),
            "action": action,
            "executed": bool(result.get("success")),
            "target": None,
            "matched_by": "intent",
            "coordinates": None,
            "message": result.get("message", ""),
        }

    target = intent.get("target", "")
    allow_app_launch = bool(intent.get("allow_app_launch"))
    app_match = _resolve_app_launch_target(target) if allow_app_launch else None

    # For "open/launch/start <app>", check UIA first, then launch installed app before falling back to OCR text
    match, matched_by, src_dims = resolve_target(target, allow_ocr=(app_match is None))
    if match is None and app_match is not None:
        launch_ref, display_name = app_match
        if not execute:
            return {
                "success": True,
                "action": "open_app",
                "executed": False,
                "target": display_name,
                "matched_by": "app_launch",
                "coordinates": None,
                "message": f"Dry run: would launch '{display_name}' ({launch_ref}).",
            }
        try:
            _launch_app(launch_ref)
            return {
                "success": True,
                "action": "open_app",
                "executed": True,
                "target": display_name,
                "matched_by": "app_launch",
                "coordinates": None,
                "message": f"Opened {display_name}.",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "action": "open_app",
                "executed": False,
                "target": display_name,
                "matched_by": "app_launch",
                "coordinates": None,
                "message": f"Failed to launch '{display_name}': {exc}",
            }

    if match is None:
        if has_gemini:
            return run_gemini_agent(
                command,
                gemini_config,
                execute=execute,
                launch_app_fn=_resolve_app_launch_target,
                exec_launch_fn=_launch_app,
            )
        return {
            "success": False,
            "action": action,
            "executed": False,
            "target": target,
            "matched_by": None,
            "coordinates": None,
            "message": f"No matching UI element found for '{target}'.",
        }

    cx, cy = match["center"]
    if not execute:
        return {
            "success": True,
            "action": action,
            "executed": False,
            "target": match.get("text", target),
            "matched_by": matched_by,
            "coordinates": [cx, cy],
            "message": f"Dry run: matched '{match.get('text', target)}' via {matched_by} at ({cx},{cy}).",
        }

    payload: dict[str, Any] = {"action": action, "x": cx, "y": cy}
    if src_dims is not None:
        payload["src_w"] = src_dims[0]
        payload["src_h"] = src_dims[1]

    result = execute_action(payload)
    return {
        "success": bool(result.get("success")),
        "action": action,
        "executed": bool(result.get("success")),
        "target": match.get("text", target),
        "matched_by": matched_by,
        "coordinates": [cx, cy],
        "message": result.get("message", ""),
    }
