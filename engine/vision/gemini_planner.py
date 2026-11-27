"""Gemini-powered Observe -> Think -> Act planner for screen reading and multi-step actions."""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any, Callable

import httpx

from engine.config import GeminiConfig
from engine.vision.service import capture_screen, execute_action
from engine.vision.uia_service import _boxes_overlap, collect_uia_elements, get_nova_window_boxes

logger = logging.getLogger("nova.gemini_planner")

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
FALLBACK_MODELS = ("gemini-2.5-flash", "gemini-2.5-flash-lite")

SYSTEM_PROMPT = """You are NOVA, a Windows desktop voice agent observing the user's live screen.
Given the current screenshot, a list of detected Windows UI Automation (UIA) controls, the user's spoken request, and any steps already executed, return ONLY a valid JSON object for the NEXT single step (or "done" when complete).

JSON schema:
{
  "status": "act" | "done" | "error",
  "action": "click" | "double_click" | "right_click" | "move" | "type" | "hotkey" | "scroll" | "open_app" | "wait",
  "element_id": integer or null,
  "x_norm": integer 0..1000 or null,
  "y_norm": integer 0..1000 or null,
  "text": string or null,
  "keys": array of strings or null,
  "amount": integer or null,
  "target": string or null,
  "reply": string
}

Rules:
1. Prefer "element_id" from the UIA list when a matching control exists (e.g. New Tab, Close, Address bar, buttons).
2. If the target icon or element is visible on the screenshot but missing from UIA, provide normalized screenshot coordinates "x_norm" (0..1000 left-to-right) and "y_norm" (0..1000 top-to-bottom).
3. For standard shortcuts like adding a new tab in a browser/editor, you may click the "+"/"New Tab" control OR use "hotkey" with ["ctrl", "t"].
4. To launch an app that is not yet open, use "open_app" with "target" (e.g. "Google Chrome", "Notepad"). After launching an app, wait/re-observe in the next step before typing or clicking inside it.
5. For "type", provide "text" (and click the input field first if it is not focused). If the user asks to search, follow typing with a "hotkey" ["enter"] step.
6. Never click the floating NOVA voice pill itself.
7. If the user only asks to read/explain/summarize what is on the screen, or once the full multi-step goal has finished, return status="done" with a clear concise "reply".
"""


def _format_uia_summary(elements: list[dict[str, Any]], limit: int = 80) -> str:
    lines: list[str] = []
    for idx, item in enumerate(elements[:limit]):
        lines.append(
            f"[{idx}] {item.get('control_type', 'Control')}: {item.get('text', '')!r} center={item.get('center')}"
        )
    return "\n".join(lines) if lines else "(no UIA controls detected)"


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    cleaned = (raw_text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        parsed = json.loads(cleaned[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("Gemini did not return a valid JSON action object.")


def _call_gemini_step(
    config: GeminiConfig,
    command: str,
    png_bytes: bytes | None,
    uia_elements: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    if not config.api_key:
        raise ValueError("Gemini API key is not configured.")

    prompt_parts: list[dict[str, Any]] = [
        {
            "text": (
                f"User command: {command}\n\n"
                f"Previous steps executed: {json.dumps(history)}\n\n"
                f"Interactive UIA controls on screen:\n{_format_uia_summary(uia_elements)}"
            )
        }
    ]
    if png_bytes:
        prompt_parts.append(
            {
                "inline_data": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(png_bytes).decode("ascii"),
                }
            }
        )

    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": prompt_parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    candidate_models = [config.model] + [
        m for m in FALLBACK_MODELS if m != config.model
    ]

    response: httpx.Response | None = None
    last_detail = ""
    last_status = 0

    with httpx.Client(timeout=config.timeout_seconds) as client:
        for model_name in candidate_models:
            url = f"{GEMINI_API_BASE}/{model_name}:generateContent"
            response = client.post(
                url,
                headers={"x-goog-api-key": config.api_key, "Content-Type": "application/json"},
                json=body,
            )
            if response.status_code < 400:
                break
            last_status = response.status_code
            last_detail = response.text
            try:
                err_json = response.json()
                last_detail = err_json.get("error", {}).get("message") or last_detail
            except Exception:  # noqa: BLE001
                pass
            if response.status_code not in {429, 503}:
                raise RuntimeError(f"Gemini API error ({last_status}): {last_detail}")

    if response is None or response.status_code >= 400:
        raise RuntimeError(f"Gemini API error ({last_status}): {last_detail}")

    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates.")
    parts = candidates[0].get("content", {}).get("parts") or []
    text_out = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return _extract_json_object(text_out)


def run_gemini_agent(
    command: str,
    config: GeminiConfig,
    *,
    execute: bool = True,
    launch_app_fn: Callable[[str], tuple[str, str] | None] | None = None,
    exec_launch_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run an Observe -> Think -> Act loop powered by Gemini multimodal + UIA."""
    if not config.api_key:
        return {
            "success": False,
            "action": "gemini",
            "executed": False,
            "target": None,
            "matched_by": None,
            "coordinates": None,
            "message": "Gemini API key not configured. Set GEMINI_API_KEY in .env and restart the engine.",
            "steps": [],
        }

    history: list[dict[str, Any]] = []
    last_coords: list[int] | None = None
    last_target: str | None = None
    last_action = "gemini"
    max_steps = config.max_steps if execute else 1

    for step_idx in range(1, max_steps + 1):
        png_bytes: bytes | None = None
        screen_w = 0
        screen_h = 0
        try:
            png_bytes, screen_w, screen_h = capture_screen()
        except Exception:  # noqa: BLE001
            logger.debug("Screenshot unavailable during Gemini step %s.", step_idx, exc_info=True)

        uia_elements = collect_uia_elements()
        excluded_boxes = get_nova_window_boxes()

        try:
            plan = _call_gemini_step(config, command, png_bytes, uia_elements, history)
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "action": last_action,
                "executed": bool(history),
                "target": last_target,
                "matched_by": "gemini",
                "coordinates": last_coords,
                "message": str(exc),
                "steps": history,
            }

        status = str(plan.get("status") or "done").lower().strip()
        reply = str(plan.get("reply") or "").strip()

        if status == "done":
            return {
                "success": True,
                "action": last_action if history else "read_screen",
                "executed": bool(history),
                "target": last_target,
                "matched_by": "gemini",
                "coordinates": last_coords,
                "message": reply or (history[-1]["message"] if history else "Done."),
                "screen_text": reply if not history else None,
                "steps": history,
            }

        if status == "error":
            return {
                "success": False,
                "action": last_action,
                "executed": bool(history),
                "target": last_target,
                "matched_by": "gemini",
                "coordinates": last_coords,
                "message": reply or "Gemini could not complete the request.",
                "steps": history,
            }

        action = str(plan.get("action") or "").lower().strip()
        last_action = action or "gemini"
        target_label = plan.get("target")
        if target_label:
            last_target = str(target_label)

        if not execute:
            return {
                "success": True,
                "action": action,
                "executed": False,
                "target": last_target,
                "matched_by": "gemini",
                "coordinates": last_coords,
                "message": f"Dry run (Gemini step 1): {action} — {reply or last_target or ''}".strip(),
                "steps": [plan],
            }

        if action == "wait":
            time.sleep(1.0)
            history.append({"step": step_idx, "action": "wait", "message": "Waited 1s."})
            continue

        if action == "open_app" and launch_app_fn and exec_launch_fn:
            app_target = str(plan.get("target") or "")
            app_match = launch_app_fn(app_target)
            if app_match is None:
                return {
                    "success": False,
                    "action": "open_app",
                    "executed": bool(history),
                    "target": app_target,
                    "matched_by": "gemini",
                    "coordinates": None,
                    "message": f"Could not find installed app '{app_target}'.",
                    "steps": history,
                }
            launch_ref, display_name = app_match
            exec_launch_fn(launch_ref)
            last_target = display_name
            history.append(
                {
                    "step": step_idx,
                    "action": "open_app",
                    "target": display_name,
                    "message": f"Opened {display_name}",
                }
            )
            time.sleep(1.6)
            continue

        if action in {"click", "double_click", "right_click", "move"}:
            cx: int | None = None
            cy: int | None = None
            src_w = 0
            src_h = 0

            elem_id = plan.get("element_id")
            if isinstance(elem_id, int) and 0 <= elem_id < len(uia_elements):
                chosen = uia_elements[elem_id]
                cx, cy = chosen["center"]
                last_target = chosen.get("text") or last_target
            elif (
                plan.get("x_norm") is not None
                and plan.get("y_norm") is not None
                and screen_w > 0
                and screen_h > 0
            ):
                x_norm = max(0, min(1000, int(plan["x_norm"])))
                y_norm = max(0, min(1000, int(plan["y_norm"])))
                cx = int((x_norm / 1000.0) * screen_w)
                cy = int((y_norm / 1000.0) * screen_h)
                src_w, src_h = screen_w, screen_h

            if cx is None or cy is None:
                return {
                    "success": False,
                    "action": action,
                    "executed": bool(history),
                    "target": last_target,
                    "matched_by": "gemini",
                    "coordinates": None,
                    "message": f"Gemini returned no valid target coordinates for '{last_target or action}'.",
                    "steps": history,
                }

            target_box = [cx - 2, cy - 2, cx + 2, cy + 2]
            if any(_boxes_overlap(target_box, ex) for ex in excluded_boxes):
                return {
                    "success": False,
                    "action": action,
                    "executed": bool(history),
                    "target": last_target,
                    "matched_by": "gemini",
                    "coordinates": [cx, cy],
                    "message": "Blocked click overlapping the NOVA voice pill.",
                    "steps": history,
                }

            payload: dict[str, Any] = {"action": action, "x": cx, "y": cy}
            if src_w > 0 and src_h > 0:
                payload["src_w"] = src_w
                payload["src_h"] = src_h
            res = execute_action(payload)
            last_coords = [cx, cy]
            history.append(
                {
                    "step": step_idx,
                    "action": action,
                    "target": last_target,
                    "coordinates": last_coords,
                    "message": res.get("message", ""),
                }
            )
            if not res.get("success"):
                return {
                    "success": False,
                    "action": action,
                    "executed": True,
                    "target": last_target,
                    "matched_by": "gemini",
                    "coordinates": last_coords,
                    "message": res.get("message", "Action failed."),
                    "steps": history,
                }
            time.sleep(0.55)
            continue

        if action in {"type", "hotkey", "scroll"}:
            res = execute_action(plan)
            history.append(
                {
                    "step": step_idx,
                    "action": action,
                    "message": res.get("message", ""),
                }
            )
            if not res.get("success"):
                return {
                    "success": False,
                    "action": action,
                    "executed": True,
                    "target": last_target,
                    "matched_by": "gemini",
                    "coordinates": last_coords,
                    "message": res.get("message", "Action failed."),
                    "steps": history,
                }
            time.sleep(0.45)
            continue

        return {
            "success": False,
            "action": action or "unknown",
            "executed": bool(history),
            "target": last_target,
            "matched_by": "gemini",
            "coordinates": last_coords,
            "message": f"Unsupported action '{action}' from Gemini.",
            "steps": history,
        }

    return {
        "success": True,
        "action": last_action,
        "executed": bool(history),
        "target": last_target,
        "matched_by": "gemini",
        "coordinates": last_coords,
        "message": history[-1]["message"] if history else "Completed steps.",
        "steps": history,
    }
