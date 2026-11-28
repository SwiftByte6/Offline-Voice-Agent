"""Rule-based multi-step task runner (screen capture + OCR/UIA + desktop actions)."""

from __future__ import annotations

import re
import time
from typing import Any

import pyautogui

from engine.vision.service import capture_screen_array, execute_action, run_ocr

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


def _find_text(items: list[dict[str, Any]], needle: str) -> dict[str, Any] | None:
    needle = needle.lower().strip()
    for it in items:
        text = str(it.get("text", "")).lower().strip()
        if needle in text or text in needle:
            return it
    return None


def task_click_text(params: dict[str, Any]) -> dict[str, Any]:
    needle = str(params.get("text") or params.get("needle") or "")
    return execute_action({"action": "click_text", "text": needle})


def task_hover_and_read(params: dict[str, Any]) -> dict[str, Any]:
    x = int(params.get("x", 0))
    y = int(params.get("y", 0))
    wait = float(params.get("wait", 0.5))
    pyautogui.moveTo(x, y)
    time.sleep(wait)
    image, _, _ = capture_screen_array()
    items = run_ocr(image)
    return {"success": True, "task": "task_hover_and_read", "items": items, "count": len(items)}


def task_scroll_to_text(params: dict[str, Any]) -> dict[str, Any]:
    needle = str(params.get("text") or params.get("needle") or "")
    max_attempts = int(params.get("max_attempts", 8))
    scroll_amount = int(params.get("scroll_amount", -300))
    for attempt in range(max_attempts):
        image, _, _ = capture_screen_array()
        hit = _find_text(run_ocr(image), needle)
        if hit:
            return {"success": True, "task": "task_scroll_to_text", "hit": hit, "attempt": attempt}
        pyautogui.scroll(scroll_amount)
        time.sleep(0.3)
    return {"success": False, "task": "task_scroll_to_text", "error": f"text not found after {max_attempts} scrolls: {needle}"}


def task_multi_step(params: dict[str, Any]) -> dict[str, Any]:
    """Execute a comma/'then'-separated multi-step voice command using OCR/UIA + desktop actions."""
    command = str(params.get("command") or "").strip()
    if not command:
        return {"success": False, "task": "multi_step", "error": "empty command"}

    clauses = [c.strip() for c in re.split(r"\s*(?:,|and then|then)\s*", command, flags=re.I) if c.strip()]
    steps_log: list[dict[str, Any]] = []
    for clause in clauses:
        low = clause.lower()
        if re.match(r"^(?:open|go to)\s+(?:my\s+)?(.+?)\s+folder$", low):
            folder = re.sub(r"^(?:open|go to)\s+(?:my\s+)?|\s+folder$", "", clause, flags=re.I).strip()
            res = execute_action({"action": "open_folder", "name": folder})
        elif low.startswith("focus ") or low.startswith("switch to "):
            win = re.sub(r"^(?:focus|switch to)\s+", "", clause, flags=re.I).strip()
            res = execute_action({"action": "window_control", "window": win, "window_action": "focus"})
        elif low.startswith("find "):
            needle = clause[5:].strip()
            res = execute_action({"action": "find_text", "text": needle})
        elif low.startswith("click "):
            target = clause[6:].strip()
            res = execute_action({"action": "click_text", "text": target})
        elif "copy" in low:
            res = execute_action({"action": "hotkey", "keys": ["ctrl", "c"]})
        elif "paste" in low:
            res = execute_action({"action": "hotkey", "keys": ["ctrl", "v"]})
        elif low.startswith("read ") or "read screen" in low:
            res = execute_action({"action": "read_screen"})
        else:
            res = {"success": True, "skipped": clause, "note": "requires LLM or explicit UI target"}
        steps_log.append({"clause": clause, "result": res})
        time.sleep(0.25)
    return {"success": all(s["result"].get("success", True) for s in steps_log), "task": "multi_step", "steps": steps_log}


def run_task(task: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    tasks = {
        "task_click_text": task_click_text,
        "task_hover_and_read": task_hover_and_read,
        "task_scroll_to_text": task_scroll_to_text,
        "task_multi_step": task_multi_step,
        "click_text": task_click_text,
        "hover_and_read": task_hover_and_read,
        "scroll_to_text": task_scroll_to_text,
        "multi_step": task_multi_step,
    }
    fn = tasks.get(task)
    if fn is None:
        return {"success": False, "error": f"unknown task {task}"}
    try:
        return fn(params)
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "task": task, "error": str(exc)}
