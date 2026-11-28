$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Make sure user and machine tools are on PATH for this session.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

# 1) Frontend dependencies
if (-not (Test-Path (Join-Path $root "node_modules"))) {
    Write-Host "Installing frontend dependencies (npm ci)..."
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
}

# 2) Python virtual environment + offline speech backend dependencies
$venvPython = Join-Path $root "engine\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating Python virtual environment..."
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 -m venv (Join-Path $root "engine\.venv")
        if ($LASTEXITCODE -ne 0) { throw "Python 3 could not create the backend virtual environment." }
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        python -m venv (Join-Path $root "engine\.venv")
        if ($LASTEXITCODE -ne 0) { throw "Python 3 could not create the backend virtual environment." }
    } else {
        throw "Python 3 is not installed. Install Python 3.11 or newer, then run this launcher again."
    }
}
Write-Host "Installing or updating offline speech backend dependencies..."
& $venvPython -m pip install -r (Join-Path $root "engine\requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Python backend dependency installation failed." }

# 3) Ensure the local LLM runtime and configured model are ready.
$ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
$ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
if (-not (Test-Path $ollamaExe) -and $ollamaCommand) {
    $ollamaExe = $ollamaCommand.Source
}
if (-not (Test-Path $ollamaExe)) {
    Write-Host "Installing Ollama from its official Windows installer..."
    $ollamaInstallerScript = Join-Path $env:TEMP "ollama-install.ps1"
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "https://ollama.com/install.ps1" -OutFile $ollamaInstallerScript
        & $ollamaInstallerScript
    } finally {
        Remove-Item -LiteralPath $ollamaInstallerScript -Force -ErrorAction SilentlyContinue
    }
    $ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
}
if (-not (Test-Path $ollamaExe)) {
    throw "Ollama installation was not found. Install Ollama and run this launcher again."
}

$ollamaTags = $null
for ($i = 0; $i -lt 6; $i++) {
    try {
        $ollamaTags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2
        break
    } catch {
        Start-Sleep -Seconds 2
    }
}
if ($null -eq $ollamaTags) {
    Write-Host "Starting the local Ollama service..."
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $ollamaTags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2
            break
        } catch {
            Start-Sleep -Seconds 2
        }
    }
}
if ($null -eq $ollamaTags) {
    throw "Ollama did not become ready at http://127.0.0.1:11434."
}
if (-not @($ollamaTags.models | Where-Object { $_.name -like "llama3.2*" }).Count) {
    Write-Host "Downloading the configured llama3.2 model (first launch only)..."
    & $ollamaExe pull llama3.2
    if ($LASTEXITCODE -ne 0) { throw "The llama3.2 model download failed." }
}

# 4) Start the speech backend if it isn't already running
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

# 5) Wait until an offline speech model is ready
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

# 6) Start the desktop app (blocks until you close it)
Write-Host "Starting P.E.K.K.A desktop app (Tauri)..."
npm.cmd exec -- tauri dev
if ($LASTEXITCODE -ne 0) { throw "Tauri failed to start." }
