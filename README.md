# NOVA — Offline Voice Agent

Floating desktop voice interface built with **Next.js (JavaScript) + React + Tailwind CSS + Tauri 2** and a local **FastAPI** voice engine. Speech recognition uses NVIDIA Parakeet through sherpa-onnx, with Faster-Whisper as an offline fallback.

## Prerequisites

- **Node.js**
- **Rust / Cargo** (for Tauri 2)
- **Python 3.11+**
- **Internet for first launch**, to install dependencies and download Ollama plus `llama3.2`

## Start Pekka

Run `run.bat`. It installs missing frontend and Python dependencies, installs Ollama if needed, ensures the local `llama3.2` model is present, starts the speech backend, waits for offline STT readiness, and launches the Tauri desktop app. The script reuses an already running Pekka backend and no longer kills processes by port number.

Pekka uses click-to-talk by default: click the pill to start recording, speak, then click again to submit. Successful turns return the pill to sleep automatically. Set `PEKKA_CONTINUOUS_LISTEN=true` only if you want optional background wake listening.

The local LLM endpoint defaults to `http://127.0.0.1:11434/v1`; set `PEKKA_LLM_BASE_URL` or `PEKKA_LLM_MODEL` to use another local model. If no local LLM is reachable at runtime, Pekka falls back to deterministic offline intent rules.

Parakeet weights are cached under `engine\.cache\parakeet`; Faster-Whisper is the fallback. Piper TTS is discovered under `engine\.cache\piper` or `%LOCALAPPDATA%\JARVIS\voice`. Otherwise Pekka uses the installed Windows System.Speech voice. Set `PEKKA_PIPER_EXE` and `PEKKA_PIPER_MODEL` to prefer local Piper files.

*(Optional: to run only the Next.js web frontend without Tauri, run `npm run dev` and open `http://localhost:3000`.)*

## 3. Useful Checks

- Health endpoint: `http://127.0.0.1:8000/health`
- Frontend lint: `pnpm lint`
