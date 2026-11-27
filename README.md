# NOVA — Offline Voice Agent

Floating desktop voice interface built with **Next.js (JavaScript) + React + Tailwind CSS + Tauri 2**, Qwen3-ASR-0.6B transcription, LFM3-1.7B task planning, OCR, and PyAutoGUI desktop actions.

## Prerequisites

- **Node.js** and **pnpm**
- **Rust / Cargo** (for Tauri 2)
- **Python 3.11+** (tested setup uses `engine/.venv`)

## 1. First-Time Setup

Install frontend dependencies:

```powershell
pnpm install
```

Create the Python virtual environment and install backend dependencies:

```powershell
python -m venv engine\.venv
.\engine\.venv\Scripts\pip.exe install -r engine\requirements.txt
```

## 2. Run NOVA (2 Terminals)

### Terminal 1 — Start the Local Agent Engine (FastAPI + Qwen3-ASR-0.6B + LFM3-1.7B)

```powershell
.\engine\.venv\Scripts\python.exe -m uvicorn engine.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

- Wait until you see both `Qwen3-ASR model 'Qwen/Qwen3-ASR-0.6B' is ready.` and `LFM3 planner is ready.`
- First launch downloads Qwen3-ASR-0.6B into `engine\.cache\qwen-asr`. Later launches use the cached model.
- The first LFM3 launch also downloads the `LFM3-1.7B-Q4_K_M.gguf` planner (about 1.1 GB) into `engine\.cache\lfm3`. It runs on CPU by default; set `NOVA_LLM_GPU_LAYERS` to offload layers on a compatible GPU.
- Set `NOVA_QWEN_ASR_OFFLINE_ONLY=true` after the first download to prevent model downloads and Hub requests.
- Set `NOVA_LLM_OFFLINE_ONLY=true` after the first LFM3 download to keep task planning fully offline.
- CPU with `float32` is the default. On a compatible GPU, set `NOVA_QWEN_ASR_DEVICE=cuda:0` and `NOVA_QWEN_ASR_DTYPE=bfloat16` before starting the engine.

### Terminal 2 — Start the NOVA Desktop App (Next.js + Tauri 2)

```powershell
pnpm exec tauri dev
```

Run `run.bat` or `run.ps1` to install or update all backend dependencies, start the speech engine, and open the desktop app. If an older speech engine is already listening on port 8000, close it before running the launcher so Qwen3-ASR can start.

## Desktop Agent Flow

Each voice request is transcribed, then the engine captures the primary screen and extracts its visible text with OCR. LFM3 receives the transcript, screen dimensions, and OCR text boxes. It returns a JSON action list, which the engine validates before executing supported PyAutoGUI actions.

NOVA works in short cycles: it observes the screen, plans up to three actions, runs ordinary actions, then captures the screen again before continuing. It includes file search, rename, move, copy, open, and URL tools for Desktop, Downloads, Documents, and Pictures.

Test a typed instruction without executing it:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/agent/run" -Method Post -ContentType "application/json" -Body '{"instruction":"click Settings","execute":false}' | ConvertTo-Json -Depth 8
```

Set `execute` to `true` to run the returned actions.

NOVA automatically performs ordinary UI and file actions. It pauses for confirmation before deleting a file, closing an app, or overwriting an existing file during rename, move, or copy.

## Debug Trace

`run.ps1` opens the local-agent backend in a visible terminal. It prints the speech transcript, OCR items, complete LLM prompts, raw LLM output, validated task plan, and PyAutoGUI execution results. Use this terminal while testing voice commands.

*(Optional: to run only the Next.js web frontend without Tauri, run `pnpm dev` and open `http://localhost:3000`.)*

## 3. Useful Checks

- Health endpoint: `http://127.0.0.1:8000/health`
- Frontend lint: `pnpm lint`
