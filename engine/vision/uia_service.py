"""Windows UI Automation element collector for labeled controls and icons."""

from __future__ import annotations

from collections import deque
import logging
from typing import Any

import uiautomation as auto

logger = logging.getLogger("nova.uia")

INTERACTIVE_CONTROL_TYPES = {
    "ButtonControl",
    "CheckBoxControl",
    "ComboBoxControl",
    "EditControl",
    "HyperlinkControl",
    "ListItemControl",
    "MenuItemControl",
    "RadioButtonControl",
    "SplitButtonControl",
    "TabItemControl",
}

EXCLUDED_WINDOW_NAMES = {"nova", "awaaz"}


def _rect_to_box(rect: Any) -> list[int] | None:
    if rect is None:
        return None
    left = int(getattr(rect, "left", 0))
    top = int(getattr(rect, "top", 0))
    right = int(getattr(rect, "right", 0))
    bottom = int(getattr(rect, "bottom", 0))
    if right <= left or bottom <= top:
        return None
    return [left, top, right, bottom]


def _boxes_overlap(box_a: list[int], box_b: list[int]) -> bool:
    return not (
        box_a[2] <= box_b[0]
        or box_a[0] >= box_b[2]
        or box_a[3] <= box_b[1]
        or box_a[1] >= box_b[3]
    )


def get_nova_window_boxes() -> list[list[int]]:
    """Return bounding boxes for visible NOVA windows so actions avoid clicking the pill."""
    boxes: list[list[int]] = []
    try:
        with auto.UIAutomationInitializerInThread():
            root = auto.GetRootControl()
            for child in root.GetChildren():
                name = (getattr(child, "Name", "") or "").strip().lower()
                if name in EXCLUDED_WINDOW_NAMES:
                    box = _rect_to_box(getattr(child, "BoundingRectangle", None))
                    if box is not None:
                        boxes.append(box)
    except Exception:  # noqa: BLE001
        logger.debug("Could not inspect NOVA window bounds via UIA.", exc_info=True)
    return boxes


def _scan_root_control(
    root_control: Any,
    max_depth: int,
    max_nodes: int,
    excluded_boxes: list[list[int]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if root_control is None:
        return items

    queue: deque[tuple[Any, int]] = deque([(root_control, 0)])
    visited = 0

    while queue and visited < max_nodes:
        control, depth = queue.popleft()
        visited += 1

        try:
            if getattr(control, "IsOffscreen", False):
                continue

            control_type = getattr(control, "ControlTypeName", "") or ""
            name = (getattr(control, "Name", "") or "").strip()
            box = _rect_to_box(getattr(control, "BoundingRectangle", None))

            if (
                depth > 0
                and name
                and control_type in INTERACTIVE_CONTROL_TYPES
                and box is not None
                and not any(_boxes_overlap(box, ex) for ex in excluded_boxes)
            ):
                items.append(
                    {
                        "text": name,
                        "control_type": control_type,
                        "confidence": 1.0,
                        "box": box,
                        "center": [int((box[0] + box[2]) / 2), int((box[1] + box[3]) / 2)],
                        "source": "uia",
                    }
                )

            if depth < max_depth:
                for child in control.GetChildren():
                    queue.append((child, depth + 1))
        except Exception:  # noqa: BLE001
            continue

    return items


def collect_uia_elements(
    max_depth: int = 8,
    max_nodes: int = 400,
) -> list[dict[str, Any]]:
    """Collect visible named UI controls from the foreground window and taskbar."""
    elements: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, int, int, int, int]] = set()

    try:
        with auto.UIAutomationInitializerInThread():
            excluded_boxes = get_nova_window_boxes()
            roots: list[Any] = []

            try:
                foreground = auto.GetForegroundControl()
                if foreground is not None:
                    fg_name = (getattr(foreground, "Name", "") or "").strip().lower()
                    if fg_name not in EXCLUDED_WINDOW_NAMES:
                        roots.append(foreground)
            except Exception:  # noqa: BLE001
                logger.debug("Foreground UIA scan skipped.", exc_info=True)

            try:
                taskbar = auto.WindowControl(searchDepth=1, ClassName="Shell_TrayWnd")
                if taskbar.Exists(0, 0):
                    if not roots or getattr(taskbar, "NativeWindowHandle", None) != getattr(
                        roots[0], "NativeWindowHandle", None
                    ):
                        roots.append(taskbar)
            except Exception:  # noqa: BLE001
                logger.debug("Taskbar UIA scan skipped.", exc_info=True)

            for root in roots:
                for item in _scan_root_control(root, max_depth, max_nodes, excluded_boxes):
                    box = item["box"]
                    key = (item["text"].lower(), box[0], box[1], box[2], box[3])
                    if key not in seen_keys:
                        seen_keys.add(key)
                        elements.append(item)
    except Exception:  # noqa: BLE001
        logger.debug("UIA collection failed; falling back to OCR.", exc_info=True)

    return elements
