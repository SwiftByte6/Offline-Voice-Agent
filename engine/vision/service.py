"""Screen capture, OCR, and desktop-action helpers for the NOVA voice agent."""

from __future__ import annotations

import base64
import io
import logging
import threading
import time
from typing import Any

import cv2
import mss
import numpy as np
import pyautogui
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

logger = logging.getLogger("nova.vision")

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

_ocr_lock = threading.Lock()
_ocr_engine: RapidOCR | None = None


def _get_ocr() -> RapidOCR:
    global _ocr_engine
    if _ocr_engine is None:
        with _ocr_lock:
            if _ocr_engine is None:
                logger.info("Initializing RapidOCR engine...")
                _ocr_engine = RapidOCR()
    return _ocr_engine


def capture_screen() -> tuple[bytes, int, int]:
    """Capture the primary monitor and return (PNG bytes, width, height)."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), img.width, img.height


def capture_screen_array() -> tuple[np.ndarray, int, int]:
    """Capture the primary monitor as an RGB numpy array plus dimensions."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        raw = sct.grab(monitor)
        img = np.array(raw)[:, :, :3][:, :, ::-1]  # BGRA -> RGB
        return img, img.shape[1], img.shape[0]


def run_ocr(image: np.ndarray | None = None) -> list[dict[str, Any]]:
    """Run OCR on an RGB image (or capture the screen) and return text + boxes."""
    if image is None:
        image, _, _ = capture_screen_array()

    # Light preprocessing to improve OCR on UI text.
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    enhanced = cv2.convertScaleAbs(gray, alpha=1.2, beta=10)

    ocr = _get_ocr()
    result, _ = ocr(enhanced)

    items: list[dict[str, Any]] = []
    if not result:
        return items

    for box, text, score in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x1, y1 = int(min(xs)), int(min(ys))
        x2, y2 = int(max(xs)), int(max(ys))
        items.append(
            {
                "text": str(text).strip(),
                "confidence": round(float(score), 3),
                "box": [x1, y1, x2, y2],
                "center": [int((x1 + x2) / 2), int((y1 + y2) / 2)],
            }
        )
    return items


def ocr_to_prompt_text(items: list[dict[str, Any]]) -> str:
    """Compact text representation of OCR results for an LLM prompt."""
    lines = []
    for it in items:
        if it["text"]:
            lines.append(f"- {it['text']} @ {it['box']}")
    return "\n".join(lines)


def _scale_point(x: int, y: int, src_w: int, src_h: int) -> tuple[int, int]:
    screen_w, screen_h = pyautogui.size()
    if src_w <= 0 or src_h <= 0:
        return x, y
    sx = screen_w / src_w
    sy = screen_h / src_h
    return int(x * sx), int(y * sy)


def execute_action(action: dict[str, Any]) -> dict[str, Any]:
    """Execute a desktop action dict. Supported: click, double_click, right_click,
    type, hotkey, scroll, move, open, navigate_url."""
    kind = str(action.get("action", "")).lower().strip()
    try:
        if kind in {"click", "double_click", "right_click"}:
            if "x" in action and "y" in action:
                x = int(action["x"])
                y = int(action["y"])
                src_w = int(action.get("src_w", 0) or 0)
                src_h = int(action.get("src_h", 0) or 0)
                rx, ry = _scale_point(x, y, src_w, src_h)
            else:
                rx, ry = pyautogui.position()
            if kind == "click":
                pyautogui.click(rx, ry)
            elif kind == "double_click":
                pyautogui.doubleClick(rx, ry)
            else:
                pyautogui.rightClick(rx, ry)
            return {"success": True, "message": f"{kind} at ({rx},{ry})"}

        if kind == "type":
            text = str(action.get("text", ""))
            pyautogui.write(text, interval=0.02)
            return {"success": True, "message": f"typed {len(text)} chars"}

        if kind == "open":
            target = str(action.get("target", "")).strip()
            if not target:
                return {"success": False, "message": "open requires a target"}
            pyautogui.press("win")
            time.sleep(0.4)
            pyautogui.write(target, interval=0.02)
            time.sleep(0.4)
            pyautogui.press("enter")
            return {"success": True, "message": f"opened {target!r} from Start"}

        if kind == "navigate_url":
            url = str(action.get("url", "")).strip()
            if not url.startswith(("https://", "http://")):
                return {"success": False, "message": "navigate_url requires an http or https URL"}
            # Give a newly launched browser time to become the foreground window.
            time.sleep(1.5)
            pyautogui.hotkey("ctrl", "l")
            pyautogui.write(url, interval=0.01)
            pyautogui.press("enter")
            return {"success": True, "message": f"navigated active browser to {url}"}

        if kind == "hotkey":
            keys = action.get("keys") or []
            if isinstance(keys, str):
                keys = [keys]
            pyautogui.hotkey(*keys)
            return {"success": True, "message": f"hotkey {keys}"}

        if kind == "scroll":
            amount = int(action.get("amount", 0))
            pyautogui.scroll(amount)
            return {"success": True, "message": f"scrolled {amount}"}

        if kind == "move":
            if "x" in action and "y" in action:
                x = int(action["x"])
                y = int(action["y"])
                src_w = int(action.get("src_w", 0) or 0)
                src_h = int(action.get("src_h", 0) or 0)
                rx, ry = _scale_point(x, y, src_w, src_h)
            else:
                rx, ry = pyautogui.position()
            pyautogui.moveTo(rx, ry, duration=0.15)
            return {"success": True, "message": f"moved to ({rx},{ry})"}

        return {"success": False, "message": f"unknown action '{kind}'"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Action failed: %s", action)
        return {"success": False, "message": str(exc)}


def screenshot_base64() -> tuple[str, int, int]:
    png_bytes, w, h = capture_screen()
    return base64.b64encode(png_bytes).decode("ascii"), w, h
