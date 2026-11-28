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

# 2) Python virtual environment + offline speech backend dependencies
$venvPython = Join-Path $root "engine\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating Python virtual environment..."
    python -m venv (Join-Path $root "engine\.venv")
}
Write-Host "Installing or updating offline speech backend dependencies..."
& (Join-Path $root "engine\.venv\Scripts\pip.exe") install -r (Join-Path $root "engine\requirements.txt")

# 3) Start the speech backend if it isn't already running
$backendReady = $false
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 2
    $health = $resp.Content | ConvertFrom-Json
    if ($health.model -like "*parakeet*" -or $health.model -like "*whisper*") {
        $backendReady = $true
        Write-Host "P.E.K.K.A speech backend already running."
    } else {
        throw "A non-P.E.K.K.A speech backend is using port 8000. Close it, then run this launcher again."
    }
} catch {
    if ($_.Exception.Message -like "A non-P.E.K.K.A*") {
        throw
    }
    Write-Host "Starting speech backend (FastAPI + Parakeet / Whisper)..."
    Start-Process -FilePath $venvPython `
        -ArgumentList "-m", "uvicorn", "engine.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log" `
        -WorkingDirectory $root -WindowStyle Hidden
}

# 4) Wait until an offline speech model is ready
Write-Host "Waiting for the offline speech model to be ready..."
for ($i = 0; $i -lt 120; $i++) {
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
