"""Windows UI Automation, window management, and Explorer folder helpers (adapted from Jarvis `uictl.py`).

Uses built-in Windows PowerShell + UIAutomationClient so controls are found and invoked by
real element name/pattern first, with RapidOCR in `service.py` as the fallback.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_PS_PRELUDE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -Namespace P -Name Dpi -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(System.IntPtr v);'
[void][P.Dpi]::SetProcessDpiAwarenessContext([IntPtr](-4))
$a = $env:PEKKA_UIA_ARG | ConvertFrom-Json
"""

_WIN_CTL_SCRIPT = _PS_PRELUDE + r"""
Add-Type -Namespace P -Name Ctl -MemberDefinition '
[DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int cmd);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr h);
[DllImport("user32.dll")] public static extern bool PostMessageW(System.IntPtr h, uint msg, System.IntPtr w, System.IntPtr l);
'
$h = [IntPtr][long]$a.hwnd
switch ($a.action) {
  'focus'    { [void][P.Ctl]::ShowWindow($h, 9); [void][P.Ctl]::SetForegroundWindow($h) }
  'minimize' { [void][P.Ctl]::ShowWindow($h, 6) }
  'maximize' { [void][P.Ctl]::ShowWindow($h, 3); [void][P.Ctl]::SetForegroundWindow($h) }
  'restore'  { [void][P.Ctl]::ShowWindow($h, 9) }
  'close'    { [void][P.Ctl]::PostMessageW($h, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) }
}
@{ ok = $true; action = $a.action } | ConvertTo-Json -Compress
"""

_UIA_SCRIPT = _PS_PRELUDE + r"""
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$AE = [Windows.Automation.AutomationElement]
$win = if ($a.hwnd) { $AE::FromHandle([IntPtr][long]$a.hwnd) } else { $AE::RootElement }
$q = ([string]$a.text).Trim().ToLower()
$found = @()
$scope = if ($a.hwnd) { [Windows.Automation.TreeScope]::Descendants } else { [Windows.Automation.TreeScope]::Children }
$all = $win.FindAll($scope, [Windows.Automation.Condition]::TrueCondition)
foreach ($e in $all) {
  $c = $e.Current
  if (-not $c.Name -or $c.IsOffscreen) { continue }
  $n = $c.Name.Trim().ToLower()
  if ($q -and -not $n.Contains($q)) { continue }
  $r = $c.BoundingRectangle
  if ($r.IsEmpty -or $r.Width -le 1 -or $r.Height -le 1) { continue }
  $found += [pscustomobject]@{
    el = $e; name = $c.Name; type = $c.ControlType.ProgrammaticName.Replace('ControlType.', '');
    x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height;
    enabled = $c.IsEnabled; exact = ($n -eq $q)
  }
  if ($found.Count -ge 80) { break }
}
$items = @($found | Sort-Object @{ e = { -not $_.exact } }, @{ e = { -not $_.enabled } })
$out = @{ window = $win.Current.Name; count = $items.Count }
if ($a.mode -eq 'type') {
  $fields = @($items | Where-Object { $_.type -in @('Edit', 'ComboBox', 'Document') })
  if ($fields.Count -eq 0) { $fields = $items }
  if ($fields.Count -eq 0) { $out.done = 'none' }
  else {
    $pick = $fields[[Math]::Min([int]$a.index, $fields.Count - 1)]
    $out.picked = @{ name = $pick.name; type = $pick.type; x = $pick.x; y = $pick.y; w = $pick.w; h = $pick.h }
    $p = $null
    if ($pick.el.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern, [ref]$p) -and -not $p.Current.IsReadOnly) {
      $p.SetValue([string]$a.value); $out.done = 'set'
    } else {
      try { $pick.el.SetFocus(); $out.done = 'focused' } catch { $out.done = 'point' }
    }
  }
} elseif ($a.mode -eq 'click') {
  if ($items.Count -eq 0) { $out.done = 'none' }
  else {
    $pick = $items[[Math]::Min([int]$a.index, $items.Count - 1)]
    $out.picked = @{ name = $pick.name; type = $pick.type; x = $pick.x; y = $pick.y; w = $pick.w; h = $pick.h }
    $out.done = 'point'
    if (-not $a.pointer) {
      $el = $pick.el
      $p = $null
      foreach ($pat in @(
        [Windows.Automation.InvokePattern]::Pattern,
        [Windows.Automation.SelectionItemPattern]::Pattern,
        [Windows.Automation.TogglePattern]::Pattern,
        [Windows.Automation.ExpandCollapsePattern]::Pattern
      )) {
        if ($el.TryGetCurrentPattern($pat, [ref]$p)) {
          if ($p -is [Windows.Automation.InvokePattern]) { $p.Invoke() }
          elseif ($p -is [Windows.Automation.SelectionItemPattern]) { $p.Select() }
          elseif ($p -is [Windows.Automation.TogglePattern]) { $p.Toggle() }
          else { if ($p.Current.ExpandCollapseState -eq 'Collapsed') { $p.Expand() } else { $p.Collapse() } }
          $out.done = 'pressed'; $out.how = $p.GetType().Name.Replace('Pattern', '')
          break
        }
      }
    }
  }
} else {
  $out.items = @($items | Select-Object -First ([int]$a.limit) | ForEach-Object {
    @{ name = $_.name; type = $_.type; x = $_.x; y = $_.y; w = $_.w; h = $_.h; enabled = $_.enabled }
  })
}
$out | ConvertTo-Json -Depth 5 -Compress
"""


def _run_ps(script: str, arg: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    env = {**os.environ, "PEKKA_UIA_ARG": json.dumps(arg)}
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=_CREATE_NO_WINDOW,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err or f"PowerShell exited with {proc.returncode}")
    raw = (proc.stdout or "").strip()
    if not raw:
        return {}
    return json.loads(raw)


def list_windows() -> list[dict[str, Any]]:
    """Return visible top-level windows with hwnd, title, and process name."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    wins: list[dict[str, Any]] = []

    def _proc_name(pid: int) -> str:
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(260)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return Path(buf.value).stem
        finally:
            kernel32.CloseHandle(handle)
        return ""

    def _cb(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return True
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        wins.append({"hwnd": int(hwnd), "title": title, "app": _proc_name(pid.value)})
        return len(wins) < 40

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return wins


def resolve_window(query: str = "") -> dict[str, Any] | None:
    """Find the best matching visible window by title or app name (or foreground if empty)."""
    wins = list_windows()
    if not wins:
        return None
    q = (query or "").strip().lower()
    if not q:
        return wins[0]
    for w in wins:
        if q == (w.get("title") or "").lower() or q == (w.get("app") or "").lower():
            return w
    for w in wins:
        if q in (w.get("title") or "").lower() or q in (w.get("app") or "").lower():
            return w
    return None


def window_control(window: str, action: str) -> dict[str, Any]:
    """focus, minimize, maximize, restore, or close a window."""
    act = (action or "").strip().lower()
    if act not in {"focus", "minimize", "maximize", "restore", "close"}:
        return {"success": False, "message": f"Unsupported window action '{action}'."}
    w = resolve_window(window)
    if w is None:
        return {"success": False, "message": f"Window '{window}' not found."}
    _run_ps(_WIN_CTL_SCRIPT, {"hwnd": w["hwnd"], "action": act})
    return {"success": True, "window": w["title"], "app": w["app"], "action": act}


def find_controls(window: str = "", text: str = "", limit: int = 30) -> dict[str, Any]:
    """Discover UI Automation controls in a window (or desktop root if window is empty)."""
    w = resolve_window(window) if window else None
    hwnd = w["hwnd"] if w else 0
    out = _run_ps(_UIA_SCRIPT, {"hwnd": hwnd, "text": text, "mode": "find", "limit": max(1, min(limit, 80))})
    return {
        "success": True,
        "window": out.get("window") or (w["title"] if w else "Desktop"),
        "matches": out.get("count", 0),
        "controls": out.get("items") or [],
    }


def uia_click_text(
    text: str,
    *,
    window: str = "",
    button: str = "left",
    double: bool = False,
    index: int = 0,
) -> dict[str, Any] | None:
    """Try clicking/invoking a control via UI Automation; returns None if not found so OCR can take over."""
    if os.name != "nt":
        return None
    w = resolve_window(window) if window else None
    if window and w is None:
        return None
    hwnd = w["hwnd"] if w else 0
    pointer = button != "left" or double
    try:
        out = _run_ps(_UIA_SCRIPT, {"hwnd": hwnd, "text": text, "mode": "click", "index": index, "pointer": pointer})
    except Exception:
        return None
    done = out.get("done")
    if done == "pressed":
        picked = out["picked"]
        return {
            "success": True,
            "text": picked["name"],
            "control": picked["type"],
            "via": "ui_automation",
            "action": out.get("how"),
        }
    if done == "point":
        import pyautogui

        p = out["picked"]
        cx, cy = p["x"] + p["w"] // 2, p["y"] + p["h"] // 2
        if double:
            pyautogui.doubleClick(cx, cy)
        elif button == "right":
            pyautogui.rightClick(cx, cy)
        else:
            pyautogui.click(cx, cy)
        return {
            "success": True,
            "text": p["name"],
            "center": [cx, cy],
            "control": p["type"],
            "via": "ui_automation",
        }
    return None


def uia_type_into(
    label: str,
    text: str,
    *,
    window: str = "",
    submit: bool = False,
    index: int = 0,
) -> dict[str, Any]:
    """Type into a field located by its UIA label."""
    if os.name != "nt":
        return {"success": False, "message": "UI Automation is only supported on Windows."}
    w = resolve_window(window) if window else None
    hwnd = w["hwnd"] if w else 0
    out = _run_ps(_UIA_SCRIPT, {"hwnd": hwnd, "text": label, "mode": "type", "value": text, "index": index})
    done = out.get("done")
    if done == "none":
        return {"success": False, "message": f"No field labelled '{label}' found."}
    import pyautogui

    if done in {"focused", "point"}:
        if done == "point":
            p = out["picked"]
            pyautogui.click(p["x"] + p["w"] // 2, p["y"] + p["h"] // 2)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.write(text, interval=0.02)
    if submit:
        pyautogui.press("enter")
    return {
        "success": True,
        "field": out["picked"]["name"],
        "how": "set_value" if done == "set" else "typed",
        "submitted": submit,
    }


def resolve_folder_path(name_or_path: str) -> Path | None:
    """Resolve an explicit path or a named folder under Desktop/Documents/Downloads/Home."""
    raw = (name_or_path or "").strip().strip('"')
    if not raw:
        return None
    direct = Path(raw).expanduser()
    if direct.is_dir():
        return direct.resolve()
    home = Path.home()
    roots = [home / "Desktop", home / "Documents", home / "Downloads", home]
    q = raw.lower()
    for root in roots:
        if not root.is_dir():
            continue
        candidate = root / raw
        if candidate.is_dir():
            return candidate.resolve()
        for child in root.iterdir():
            if child.is_dir() and q in child.name.lower():
                return child.resolve()
    return None


def open_folder(name_or_path: str) -> dict[str, Any]:
    """Open a folder in File Explorer (or file manager)."""
    folder = resolve_folder_path(name_or_path)
    if folder is None:
        return {"success": False, "message": f"Folder '{name_or_path}' not found."}
    if os.name == "nt":
        subprocess.Popen(["explorer.exe", str(folder)], creationflags=_CREATE_NO_WINDOW)
    return {"success": True, "path": str(folder), "message": f"Opened folder {folder.name}"}


def get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Return (left, top, right, bottom) for a window handle on Windows."""
    if os.name != "nt" or not hwnd:
        return None
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    return None


def read_window(window: str = "") -> dict[str, Any]:
    """Capture a specific window (or foreground window) and read its text via RapidOCR."""
    from engine.vision.service import capture_screen_array, run_ocr

    w = resolve_window(window)
    image, screen_w, screen_h = capture_screen_array()
    rect = get_window_rect(w["hwnd"]) if w else None
    if rect is not None:
        l, t, r, b = rect
        l, t, r, b = max(0, l), max(0, t), min(screen_w, r), min(screen_h, b)
        if r > l and b > t:
            image = image[t:b, l:r]
    items = run_ocr(image)
    text = "\n".join(it["text"] for it in items if it.get("text"))
    return {
        "success": True,
        "window": w["title"] if w else "Screen",
        "app": w["app"] if w else "",
        "text": text[:8000],
        "lines": len(items),
    }


def wait_for_window(title: str = "", seconds: float = 5.0) -> dict[str, Any]:
    """Wait until a window matching `title` is visible/foreground (up to 15s)."""
    import time

    limit = max(0.5, min(float(seconds), 15.0))
    q = (title or "").strip().lower()
    start = time.monotonic()
    while time.monotonic() - start < limit:
        wins = list_windows()
        if q:
            hit = next((w for w in wins if q in (w.get("title") or "").lower() or q in (w.get("app") or "").lower()), None)
            if hit:
                return {"success": True, "found": True, "window": hit["title"], "app": hit["app"], "waited_s": round(time.monotonic() - start, 1)}
        elif wins:
            return {"success": True, "found": True, "window": wins[0]["title"], "app": wins[0]["app"], "waited_s": round(time.monotonic() - start, 1)}
        time.sleep(0.25)
    return {"success": False, "found": False, "waited_s": round(limit, 1), "message": f"Window '{title}' did not appear."}


def select_files(folder_name_or_path: str, *, name_contains: str = "", extension: str = "") -> dict[str, Any]:
    """Find matching files in a folder and open/select them in Explorer (Jarvis-style)."""
    folder = resolve_folder_path(folder_name_or_path)
    if folder is None:
        return {"success": False, "message": f"Folder '{folder_name_or_path}' not found."}
    ext = (extension or "").lower().lstrip(".").lstrip("*.")
    needle = (name_contains or "").lower().strip()
    matches: list[Path] = []
    for item in sorted(folder.iterdir()):
        if ext and item.suffix.lower().lstrip(".") != ext:
            continue
        if needle and needle not in item.name.lower():
            continue
        if item.is_file() or ext:
            matches.append(item)
    if os.name == "nt":
        if matches:
            subprocess.Popen(["explorer.exe", "/select,", str(matches[0])], creationflags=_CREATE_NO_WINDOW)
        else:
            subprocess.Popen(["explorer.exe", str(folder)], creationflags=_CREATE_NO_WINDOW)
    return {
        "success": True,
        "folder": str(folder),
        "selected": [p.name for p in matches[:20]],
        "count": len(matches),
    }
