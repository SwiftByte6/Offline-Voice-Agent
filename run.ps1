$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Make sure Rust/Cargo (installed via rustup) is on PATH for this session.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

# 1) Frontend dependencies
if (-not (Test-Path (Join-Path $root "node_modules"))) {
    Write-Host "Installing frontend dependencies (pnpm install)..."
    pnpm install
}

# 2) Python virtual environment + Qwen3-ASR backend dependencies
$venvPython = Join-Path $root "engine\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating Python virtual environment..."
    python -m venv (Join-Path $root "engine\.venv")
}
Write-Host "Installing or updating local-agent backend dependencies..."
& (Join-Path $root "engine\.venv\Scripts\pip.exe") install -r (Join-Path $root "engine\requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Backend dependency installation failed. The agent was not started."
}

# 3) Start the speech backend if it isn't already running
$backendReady = $false
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 2
    $health = $resp.Content | ConvertFrom-Json
    if ($health.agent_version -eq "desktop-agent-v6" -and $health.model -like "*Qwen3-ASR*" -and $health.llm_model -like "*LFM3*") {
        $backendReady = $true
        Write-Host "Qwen3-ASR and LFM3 local agent backend already running."
    } else {
        throw "An older or incompatible backend is using port 8000. Close it, then run this launcher again."
    }
} catch {
    if ($_.Exception.Message -like "An older or incompatible backend*") {
        throw
    }
    Write-Host "Starting local agent backend (FastAPI + Qwen3-ASR + LFM3)..."
    Start-Process -FilePath $venvPython `
        -ArgumentList "-m", "uvicorn", "engine.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log" `
        -WorkingDirectory $root -WindowStyle Normal
}

# 4) Wait until Qwen3-ASR and LFM3 are ready
Write-Host "Waiting for Qwen3-ASR-0.6B and LFM3-1.7B to be ready..."
for ($i = 0; $i -lt 180; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 2
        $json = $resp.Content | ConvertFrom-Json
        if ($json.ready) {
            Write-Host "Backend ready."
            $backendReady = $true
            break
        }
    } catch { }
    Start-Sleep -Seconds 2
}

if (-not $backendReady) {
    Write-Warning "Backend did not become ready in time. Starting app anyway..."
}

# 5) Start the NOVA desktop app (blocks until you close it)
Write-Host "Starting NOVA desktop app (Tauri)..."
pnpm exec tauri dev
