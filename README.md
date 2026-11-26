# NOVA — Offline Voice Agent

Floating desktop voice interface built with **Next.js (JavaScript) + React + Tailwind CSS + Tauri 2** and a local **FastAPI + Faster-Whisper** speech recognition backend.

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

### Terminal 1 — Start the Python Speech Engine (FastAPI + Faster-Whisper)

```powershell
.\engine\.venv\Scripts\python.exe -m uvicorn engine.main:app --host 127.0.0.1 --port 8000
```

- Wait until you see `Faster-Whisper model 'base' is ready.`
- First launch downloads the `base` model into `engine\.cache\whisper`. Subsequent runs work completely offline.

### Terminal 2 — Start the NOVA Desktop App (Next.js + Tauri 2)

```powershell
pnpm exec tauri dev
```

*(Optional: to run only the Next.js web frontend without Tauri, run `pnpm dev` and open `http://localhost:3000`.)*

## 3. Useful Checks

- Health endpoint: `http://127.0.0.1:8000/health`
- Frontend lint: `pnpm lint`
