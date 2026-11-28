# NOVA — Offline Voice Agent

Floating desktop voice interface built with **Next.js (JavaScript) + React + Tailwind CSS + Tauri 2** and a local **FastAPI** voice engine. Speech recognition uses NVIDIA Parakeet through sherpa-onnx, with Faster-Whisper as an offline fallback.

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

### Terminal 1 — Start the Python Speech Engine (FastAPI + Parakeet / Whisper)

```powershell
.\engine\.venv\Scripts\python.exe -m uvicorn engine.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

- The engine loads Parakeet first and tries the cached Faster-Whisper model if Parakeet is unavailable. Parakeet weights are cached under `engine\.cache\parakeet`.
- Pekka uses click-to-talk by default: click the pill to start recording, speak, then click again to send the audio through offline STT and the voice pipeline. Set `PEKKA_CONTINUOUS_LISTEN=true` only if you want optional background wake listening.
- To enable LLM understanding offline, install Ollama, download a model once with `ollama pull llama3.2`, and keep the local service running. Pekka uses the Ollama-compatible endpoint at `http://127.0.0.1:11434/v1` by default; set `PEKKA_LLM_BASE_URL` or `PEKKA_LLM_MODEL` to use another local model. Without a reachable local LLM, Pekka falls back to deterministic offline intent rules.
- Piper TTS is discovered under `engine\.cache\piper` or `%LOCALAPPDATA%\JARVIS\voice`. Otherwise Pekka uses the installed Windows System.Speech voice as an offline fallback. Set `PEKKA_PIPER_EXE` and `PEKKA_PIPER_MODEL` to prefer local Piper files.

### Terminal 2 — Start the NOVA Desktop App (Next.js + Tauri 2)

```powershell
pnpm exec tauri dev
```

Run `run.bat` or `run.ps1` to start the speech engine and open the desktop app. `run.ps1` installs or updates backend dependencies. If another service is listening on port 8000, close it before launching Pekka.

*(Optional: to run only the Next.js web frontend without Tauri, run `pnpm dev` and open `http://localhost:3000`.)*

## 3. Useful Checks

- Health endpoint: `http://127.0.0.1:8000/health`
- Frontend lint: `pnpm lint`
