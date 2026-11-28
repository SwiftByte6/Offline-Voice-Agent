"""Screen capture, OCR, desktop-action, and screen-understanding helpers for P.E.K.K.A.

Layers:
  1. Raw screenshot (MSS)
  2. OCR text map (RapidOCR, top-to-bottom reading order)
  3. Click-by-text (Windows UI Automation first via uia.py, RapidOCR fallback)
  4. Change detection (snapshot + screen_changed)
"""

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

logger = logging.getLogger("pekka.vision")

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
        img = np.array(raw)[:, :, :3][:, :, ::-1]
        return img, img.shape[1], img.shape[0]


def screenshot_base64() -> tuple[str, int, int]:
    """Return (base64 PNG string, width, height) of the primary monitor."""
    png_bytes, w, h = capture_screen()
    return base64.b64encode(png_bytes).decode("ascii"), w, h


def run_ocr(image: np.ndarray | None = None) -> list[dict[str, Any]]:
    """Run OCR on an RGB image (or capture the screen) and return text + boxes in reading order."""
    if image is None:
        image, _, _ = capture_screen_array()

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
    items.sort(key=lambda it: (it["box"][1] // 12, it["box"][0]))
    return items


def read_screen_text(image: np.ndarray | None = None) -> str:
    """Plain reading-order text from the screen."""
    items = run_ocr(image)
    return "\n".join(it["text"] for it in items if it["text"])


def find_text_on_screen(
    query: str,
    image: np.ndarray | None = None,
    exact: bool = False,
) -> dict[str, Any] | None:
    """Find the first visible element whose text matches `query`."""
    items = run_ocr(image)
    q = query.strip().lower()
    for it in items:
        if it["text"].strip().lower() == q:
            return it
    if not exact:
        for it in items:
            if q in it["text"].strip().lower():
                return it
    return None


def snapshot() -> np.ndarray:
    """Tiny greyscale thumbnail of the screen for before/after comparison."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        raw = sct.grab(monitor)
        img = np.array(raw)[:, :, :3]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (192, 108), interpolation=cv2.INTER_AREA)


def screen_changed(before: np.ndarray, after: np.ndarray | None = None, threshold: float = 0.6) -> bool:
    """Whether the screen visibly changed between two snapshots."""
    if after is None:
        after = snapshot()
    diff = cv2.absdiff(before, after).astype(np.float32)
    if float(diff.mean()) > threshold:
        return True
    return bool((diff > 40).any())


def click_text_on_screen(
    query: str,
    button: str = "left",
    double: bool = False,
    exact: bool = False,
    window: str = "",
) -> dict[str, Any]:
    """Find text via Windows UI Automation first, then RapidOCR, and click it with change detection."""
    before = snapshot()
    try:
        from engine.vision.uia import uia_click_text

        uia_hit = uia_click_text(query, window=window, button=button, double=double)
    except Exception:  # noqa: BLE001
        uia_hit = None
    if uia_hit is not None:
        time.sleep(0.35)
        changed = screen_changed(before)
        uia_hit["screen_changed"] = changed
        if not changed:
            uia_hit["note"] = "Nothing visibly changed after the UIA action. Verify with read_screen."
        return uia_hit

    hit = find_text_on_screen(query, exact=exact)
    if hit is None:
        items = run_ocr()
        visible = "; ".join(it["text"] for it in items[:20])
        return {"success": False, "message": f"'{query}' not found on screen. Visible text: {visible}"}
    cx, cy = hit["center"]
    try:
        if double:
            pyautogui.doubleClick(cx, cy)
        elif button == "right":
            pyautogui.rightClick(cx, cy)
        else:
            pyautogui.click(cx, cy)
        time.sleep(0.35)
        changed = screen_changed(before)
        result: dict[str, Any] = {
            "success": True,
            "text": hit["text"],
            "center": [cx, cy],
            "via": "ocr",
            "screen_changed": changed,
        }
        if not changed:
            result["note"] = "Nothing visibly changed after the click. Verify with read_screen."
        return result
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "message": str(exc)}


def _scale_point(x: int, y: int, src_w: int, src_h: int) -> tuple[int, int]:
    screen_w, screen_h = pyautogui.size()
    if src_w <= 0 or src_h <= 0:
        return x, y
    return int(x * (screen_w / src_w)), int(y * (screen_h / src_h))


def execute_action(action: dict[str, Any]) -> dict[str, Any]:
    """Execute a desktop action dict (UIA, OCR, mouse, keyboard, window, or folder control)."""
    kind = str(action.get("action", "")).lower().strip()
    try:
        if kind in {"click", "double_click", "right_click"}:
            if action.get("text"):
                btn = "right" if kind == "right_click" else "left"
                return click_text_on_screen(
                    str(action["text"]),
                    button=btn,
                    double=(kind == "double_click"),
                    window=str(action.get("window", "")),
                )
            if "x" in action and "y" in action:
                rx, ry = _scale_point(int(action["x"]), int(action["y"]), int(action.get("src_w") or 0), int(action.get("src_h") or 0))
            else:
                rx, ry = pyautogui.position()
            before = snapshot()
            if kind == "click":
                pyautogui.click(rx, ry)
            elif kind == "double_click":
                pyautogui.doubleClick(rx, ry)
            else:
                pyautogui.rightClick(rx, ry)
            time.sleep(0.3)
            return {"success": True, "message": f"{kind} at ({rx},{ry})", "screen_changed": screen_changed(before)}

        if kind == "click_text":
            text = str(action.get("text", "")).strip()
            if not text:
                return {"success": False, "message": "click_text requires 'text'"}
            return click_text_on_screen(
                text,
                button=str(action.get("button", "left")),
                double=bool(action.get("double", False)),
                exact=bool(action.get("exact", False)),
                window=str(action.get("window", "")),
            )

        if kind == "read_screen":
            return {"success": True, "text": read_screen_text()}

        if kind == "find_text":
            query = str(action.get("text", "")).strip()
            hit = find_text_on_screen(query, exact=bool(action.get("exact", False)))
            return {"success": True, "found": True, **hit} if hit else {"success": True, "found": False, "message": f"'{query}' not visible on screen"}

        if kind == "list_windows":
            from engine.vision.uia import list_windows

            wins = list_windows()
            return {"success": True, "windows": wins, "count": len(wins)}

        if kind == "window_control":
            from engine.vision.uia import window_control

            return window_control(
                str(action.get("window", "")),
                str(action.get("window_action") or action.get("subaction") or "focus"),
            )

        if kind == "find_controls":
            from engine.vision.uia import find_controls

            return find_controls(
                window=str(action.get("window", "")),
                text=str(action.get("text", "")),
                limit=int(action.get("limit") or 30),
            )

        if kind == "type_into":
            from engine.vision.uia import uia_type_into

            return uia_type_into(
                label=str(action.get("label", "")),
                text=str(action.get("text", "")),
                window=str(action.get("window", "")),
                submit=bool(action.get("submit", False)),
            )

        if kind == "open_folder":
            from engine.vision.uia import open_folder

            return open_folder(str(action.get("path") or action.get("name") or ""))

        if kind == "read_window":
            from engine.vision.uia import read_window

            return read_window(str(action.get("window") or ""))

        if kind == "wait_for_window":
            from engine.vision.uia import wait_for_window

            return wait_for_window(
                title=str(action.get("title") or action.get("window") or ""),
                seconds=float(action.get("seconds") or 5.0),
            )

        if kind == "select_files":
            from engine.vision.uia import select_files

            return select_files(
                str(action.get("folder") or action.get("path") or action.get("name") or ""),
                name_contains=str(action.get("name_contains") or action.get("contains") or ""),
                extension=str(action.get("extension") or ""),
            )

        if kind == "mouse_drag":
            x1, y1 = _scale_point(int(action.get("x1", 0)), int(action.get("y1", 0)), int(action.get("src_w") or 0), int(action.get("src_h") or 0))
            x2, y2 = _scale_point(int(action.get("x2", 0)), int(action.get("y2", 0)), int(action.get("src_w") or 0), int(action.get("src_h") or 0))
            pyautogui.moveTo(x1, y1, duration=0.1)
            pyautogui.dragTo(x2, y2, duration=0.25, button="left")
            return {"success": True, "message": f"dragged from ({x1},{y1}) to ({x2},{y2})"}

        if kind == "type":
            text = str(action.get("text", ""))
            pyautogui.write(text, interval=0.02)
            return {"success": True, "message": f"typed {len(text)} chars"}

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
                rx, ry = _scale_point(int(action["x"]), int(action["y"]), int(action.get("src_w") or 0), int(action.get("src_h") or 0))
            else:
                rx, ry = pyautogui.position()
            pyautogui.moveTo(rx, ry, duration=0.15)
            return {"success": True, "message": f"moved to ({rx},{ry})"}

        if kind == "screenshot":
            b64, w, h = screenshot_base64()
            return {"success": True, "image_b64": b64, "width": w, "height": h}

        return {"success": False, "message": f"unknown action '{kind}'"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Action failed: %s", action)
        return {"success": False, "message": str(exc)}
