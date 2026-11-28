"""Tool execution for P.E.K.K.A. Permission layer runs before this."""

from __future__ import annotations

import asyncio
from typing import Any

from engine.vision.service import capture_screen_array, execute_action, run_ocr, screenshot_base64
from .intent import Intent


class ToolExecutionError(RuntimeError):
    """Raised when a tool execution fails."""


class ToolExecutor:
    async def execute(self, intent: Intent) -> dict[str, Any]:
        name = intent.tool_name
        args = intent.tool_args
        try:
            if name == "pekka_act":
                result = await asyncio.to_thread(execute_action, args)
                return {"ok": bool(result.get("success", True)), "result": result}
            if name == "pekka_ocr":
                image, width, height = await asyncio.to_thread(capture_screen_array)
                items = await asyncio.to_thread(run_ocr, image)
                return {"ok": True, "result": {"items": items, "count": len(items), "width": width, "height": height}}
            if name == "pekka_screen":
                image_b64, width, height = await asyncio.to_thread(screenshot_base64)
                return {"ok": True, "result": {"image": image_b64, "width": width, "height": height}}
            if name == "pekka_run_task":
                return await self._run_task(args)
            return {"ok": False, "error": f"unknown tool {name}"}
        except Exception as exc:  # noqa: BLE001
            raise ToolExecutionError(str(exc)) from exc

    async def _run_task(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            from engine.agent.runner import run_task  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"task runner not yet installed (Step 4): {exc}"}
        task = str(args.get("task") or "")
        params = args.get("params") if isinstance(args.get("params"), dict) else {}
        result = await asyncio.to_thread(run_task, task, params)
        return {"ok": bool(result.get("success", True)), "result": result}
