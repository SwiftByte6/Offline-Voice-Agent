# NOVA — Offline Voice Agent

Floating desktop voice interface built with **Next.js (JavaScript) + React + Tailwind CSS + Tauri 2** and a local **FastAPI + Qwen3-ASR-0.6B** speech recognition backend.

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

### Terminal 1 — Start the Python Speech Engine (FastAPI + Qwen3-ASR-0.6B)

```powershell
.\engine\.venv\Scripts\python.exe -m uvicorn engine.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

- Wait until you see `Qwen3-ASR model 'Qwen/Qwen3-ASR-0.6B' is ready.`
- First launch downloads Qwen3-ASR-0.6B into `engine\.cache\qwen-asr`. Later launches use the cached model.
- Set `NOVA_QWEN_ASR_OFFLINE_ONLY=true` after the first download to prevent model downloads and Hub requests.
- CPU with `float32` is the default. On a compatible GPU, set `NOVA_QWEN_ASR_DEVICE=cuda:0` and `NOVA_QWEN_ASR_DTYPE=bfloat16` before starting the engine.

### Terminal 2 — Start the NOVA Desktop App (Next.js + Tauri 2)

```powershell
pnpm exec tauri dev
```

Run `run.bat` or `run.ps1` to install or update all backend dependencies, start the speech engine, and open the desktop app. If an older speech engine is already listening on port 8000, close it before running the launcher so Qwen3-ASR can start.

*(Optional: to run only the Next.js web frontend without Tauri, run `pnpm dev` and open `http://localhost:3000`.)*

## 3. Useful Checks

- Health endpoint: `http://127.0.0.1:8000/health`
- Frontend lint: `pnpm lint`
