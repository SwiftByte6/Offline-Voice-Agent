# NOVA — Offline Voice + Hybrid UI Automation & OCR Integration Plan

This plan explains how to connect the existing **Qwen3-ASR** voice pipeline with **Windows UI Automation (`uiautomation`)**, the existing **RapidOCR + OpenCV** text detector, and **PyAutoGUI** desktop actions into a single offline voice-agent workflow.

---

## 1. Current Project State

| Layer | Current Implementation | Files |
| :--- | :--- | :--- |
| **Desktop Floating UI** | Compact `GlassSurface` mic trigger (`52×52`) expanding into a live-waveform voice pill (`224×52` / `308×58`) inside Tauri 2 (`340×96`) | [FloatingWindow.jsx](components/floating/FloatingWindow.jsx), [GlassSurface.jsx](components/floating/GlassSurface.jsx), [useVoiceRecorder.js](hooks/useVoiceRecorder.js), [tauriWindow.js](lib/tauriWindow.js) |
| **Frontend API Client** | Polls `GET /health` and posts recorded audio blobs to `POST /api/transcribe` at `http://127.0.0.1:8000` | [speechApi.js](lib/speechApi.js) |
| **Speech Recognition** | FastAPI + `Qwen/Qwen3-ASR-0.6B` (`qwen-asr==0.0.6`), cached locally under `engine/.cache/qwen-asr/model` | [engine/main.py](engine/main.py), [engine/config.py](engine/config.py), [engine/speech/qwen_asr_service.py](engine/speech/qwen_asr_service.py) |
| **Screen & OCR** | `mss` screen capture, OpenCV grayscale/contrast preprocessing, and `RapidOCR` (`rapidocr-onnxruntime`) returning `{ text, confidence, box, center }` | [engine/vision/service.py](engine/vision/service.py), [engine/api/routes.py](engine/api/routes.py) |
| **Desktop Executor** | `pyautogui` (`click`, `double_click`, `right_click`, `type`, `hotkey`, `scroll`, `move`) via `POST /api/act` | [engine/vision/service.py](engine/vision/service.py), [engine/api/routes.py](engine/api/routes.py) |

### Current Gaps
1. **Voice and Vision/Action are disconnected**: `FloatingWindow.jsx` stops after `transcribeAudioBlob()` returns text; it never invokes `/api/ocr` or `/api/act`.
2. **Text-only detection**: `RapidOCR` reads visible characters only. Unlabeled icons (e.g., settings gear, close `×`, back arrow, search magnifying glass, taskbar icons) are not detected by pure OCR.

---

## 2. Target Architecture (Partial / Hybrid Switch)

Instead of replacing `RapidOCR + OpenCV` completely with `uiautomation`, use a **two-pass hybrid pipeline** triggered only on demand when a voice command finishes:

```text
Voice Pill (FloatingWindow.jsx)
  │  POST /api/transcribe (audio blob)
  ▼
Qwen3-ASR-0.6B (qwen_asr_service.py)
  │  transcript text (e.g. "click settings")
  ▼
Command Router (/api/voice-act)
  ├─► Parse intent (action + target/text)
  │
  ├─► Pass 1: Windows UI Automation (uiautomation)
  │     Queries foreground window + taskbar controls for accessible Name + box
  │     (Fast ~10–30 ms on CPU; resolves labeled buttons & icon-only controls)
  │
  ├─► Pass 2 (Fallback): RapidOCR + OpenCV (run_ocr)
  │     Captures screen via mss & reads visible text when UIA has no match
  │     (Handles custom canvases, web widgets, images, PDFs)
  │
  ├─► Pass 3 (Optional): pyautogui.locateCenterOnScreen()
  │     Matches saved PNG templates via OpenCV for recurring custom icons
  │
  ▼
Action Executor (execute_action via PyAutoGUI / UIA Invoke)
  │  Scales coordinates & performs click / type / hotkey / scroll
  ▼
Voice Pill displays action confirmation or error
```

### Why Hybrid Instead of Full Replacement
- **Why add `uiautomation`**: Most Windows native controls, Electron/VS Code buttons, browser toolbars, and taskbar icons expose their accessibility `Name` (e.g., `"Settings"`, `"Close"`, `"Minimize"`, `"New Tab"`) even when no text is drawn on the icon. Querying UIA is native and near-instant on CPU.
- **Why keep `RapidOCR + OpenCV`**: Custom-drawn canvases, images, PDFs, remote sessions, and unlabeled web elements often expose empty accessibility trees. `RapidOCR` already works offline on CPU and covers those cases.
- **Why avoid heavy VLMs by default**: `Qwen/Qwen3-ASR-0.6B` already runs on CPU (`float32`). Adding a multi-gigabyte VLM for every frame would slow CPU responsiveness; keep VLM/OmniParser as an optional GPU-only Stage 4 if needed later.

---

## 3. Step-by-Step Integration Plan

### Phase 1: Add Windows UI Automation (`engine/vision/uia_service.py`)
1. **Add dependency** in [engine/requirements.txt](engine/requirements.txt):
   - Add `uiautomation>=2.0.18` (lightweight Python wrapper around Windows UIAutomation COM APIs).
   - Install into `engine/.venv`:
     ```powershell
     .\engine\.venv\Scripts\pip.exe install -r engine\requirements.txt
     ```
2. **Create `engine/vision/uia_service.py`**:
   - Implement `collect_uia_elements(max_depth: int = 8) -> list[dict]` scanning:
     - The active foreground window (`uiautomation.GetForegroundControl()`)
     - The Windows taskbar (`Shell_TrayWnd`)
   - Filter to interactive/named control types (`ButtonControl`, `MenuItemControl`, `TabItemControl`, `EditControl`, `HyperlinkControl`, `ListItemControl`, `CheckBoxControl`, `ComboBoxControl`).
   - Normalize each visible control (non-zero bounding box on screen) into the exact same shape as `run_ocr()`:
     ```python
     {
         "text": control_name.strip(),
         "control_type": control.ControlTypeName,
         "confidence": 1.0,
         "box": [left, top, right, bottom],
         "center": [int((left + right) / 2), int((top + bottom) / 2)],
         "source": "uia",
     }
     ```
   - Also wrap COM initialization safely (`uiautomation.UIAutomationInitializerInThread()`) because FastAPI runs sync helpers inside `asyncio.to_thread(...)` worker threads.

---

### Phase 2: Build the Command & Grounding Router (`engine/vision/agent_router.py`)
1. **Intent Parsing**:
   - Start with fast deterministic parsing for common voice commands (zero extra model overhead):
     - `click <target>` / `open <target>` / `tap <target>` → `action = "click"`, `target = <target>`
     - `double click <target>` → `action = "double_click"`
     - `right click <target>` → `action = "right_click"`
     - `type <text>` / `write <text>` → `action = "type"`, `text = <text>`
     - `press <keys>` → `action = "hotkey"` (e.g., `"copy"` → `["ctrl", "c"]`, `"enter"` → `["enter"]`)
     - `scroll up` / `scroll down` → `action = "scroll"`
     - `read screen` / `what is on screen` → return `ocr_to_prompt_text()` without clicking
   - *(Optional later)*: If a command doesn't match deterministic rules, pass the transcript + `ocr_to_prompt_text(items)` to a small local instruct LLM (e.g., via Ollama or `llama.cpp`) to emit structured JSON `{ "action": ..., "target": ..., "text": ... }`.
2. **Target Matching (Hybrid Cascade)**:
   - Normalize query and candidate strings (lowercase, strip punctuation).
   - **Pass 1 (UIA)**: Run `collect_uia_elements()` and score exact → substring → fuzzy (`difflib.SequenceMatcher`) matches against `text`.
   - **Pass 2 (RapidOCR fallback)**: Only if Pass 1 score is below threshold (e.g., `< 0.75`), run `run_ocr()` from [engine/vision/service.py](engine/vision/service.py) and match against OCR items.
   - **Pass 3 (Optional icon templates)**: If neither UIA nor OCR matches, optionally check saved icon templates in `engine/vision/templates/<name>.png` using `pyautogui.locateCenterOnScreen(..., confidence=0.8, grayscale=True)`.
3. **Safety & Coordinate Guardrails**:
   - Exclude bounding boxes overlapping the NOVA floating pill window (`NOVA` title / bottom-center window rect) so a voice command cannot accidentally click the pill itself.
   - Pass `src_w, src_h` consistently from `capture_screen_array()` (or native screen coordinates for UIA so `_scale_point()` does not double-scale; tag UIA boxes with actual screen `(w, h)`).
   - Keep `pyautogui.FAILSAFE = True` enabled in [engine/vision/service.py](engine/vision/service.py).

---

### Phase 3: Expose the Voice-Action Endpoint (`engine/api/routes.py`)
1. **Keep existing endpoints intact** (`/health`, `/api/transcribe`, `/api/screen`, `/api/ocr`, `/api/act`) so [smoke_test.ps1](smoke_test.ps1) and direct transcription continue working.
2. **Add `POST /api/voice-act`** in [engine/api/routes.py](engine/api/routes.py):
   - Accepts JSON `{ "command": "...", "execute": true }`.
   - Runs the hybrid UIA → RapidOCR grounding router in `asyncio.to_thread(...)`.
   - Returns:
     ```json
     {
       "success": true,
       "action": "click",
       "target": "Settings",
       "matched_by": "uia",
       "coordinates": [1840, 1052],
       "message": "click at (1840,1052)"
     }
     ```
   - *(Optional optimization)*: Allow `POST /api/transcribe?act=true` or a combined endpoint if you want transcription + action in a single HTTP round-trip.

---

### Phase 4: Wire the Voice Pill Frontend (`lib/speechApi.js` & `components/floating/FloatingWindow.jsx`)
1. **Add API helper** in [lib/speechApi.js](lib/speechApi.js):
   - Add `executeVoiceCommand(command, { execute = true, timeoutMs = 15000, signal } = {})` posting to `${baseUrl}/api/voice-act`.
2. **Update `submitAudioForTranscription` in [FloatingWindow.jsx](components/floating/FloatingWindow.jsx)**:
   - Keep `transcribeAudioBlob()` as step 1 so you still get `{ text, language, duration }`.
   - Pass non-empty `result.text` to `executeVoiceCommand(result.text)` when agent mode is active (or toggle between **Dictate** and **Act** inside the pill).
   - Display concise feedback in the compact `308×58` pill (e.g., `"Clicked Settings (UIA)"` or `"No matching UI target for '...'"` alongside the transcript).

---

## 4. Verification Plan

1. **Unit & Backend Smoke Checks**:
   - Add a `POST /api/voice-act` dry-run (`"execute": false`) test case to [smoke_test.ps1](smoke_test.ps1) verifying UIA + RapidOCR grounding returns valid coordinates without moving the cursor during automated tests.
   - Verify COM threading in FastAPI by sending multiple sequential `/api/voice-act` requests under `uvicorn`.
2. **End-to-End Voice Agent Test**:
   - Start the backend (`uvicorn engine.main:app --host 127.0.0.1 --port 8000`) and Tauri app (`pnpm exec tauri dev`).
   - Test an **icon-only button** (e.g., *"click Settings"* or *"click Close"*) → verify `matched_by: "uia"` resolves and clicks it.
   - Test **on-screen text in an image/browser canvas** → verify `matched_by: "ocr"` falls back to `RapidOCR` and clicks it.
   - Test **`"type hello world"`** → verify `pyautogui.write` types into the focused field.
3. **Frontend Checks**:
   - Run `npm run lint` and `npx --no-install next typegen` after frontend edits.
