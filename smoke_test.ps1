$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8000"

function Test-Endpoint($name, $script) {
    try {
        & $script
        Write-Host "[PASS] $name" -ForegroundColor Green
    } catch {
        Write-Host "[FAIL] $name : $($_.Exception.Message)" -ForegroundColor Red
        throw
    }
}

Test-Endpoint "health" {
    $r = Invoke-WebRequest "$base/health" -UseBasicParsing
    $j = $r.Content | ConvertFrom-Json
    if (-not $j.ready) { throw "backend not ready" }
}

Test-Endpoint "screen capture" {
    $r = Invoke-WebRequest "$base/api/screen" -UseBasicParsing
    $j = $r.Content | ConvertFrom-Json
    if (-not $j.image -or $j.width -le 0 -or $j.height -le 0) { throw "bad screen payload" }
}

Test-Endpoint "ocr" {
    $r = Invoke-WebRequest "$base/api/ocr" -Method POST -UseBasicParsing
    $j = $r.Content | ConvertFrom-Json
    if ($null -eq $j.items) { throw "no items field" }
}

Test-Endpoint "act move" {
    $body = '{"action":"move","x":100,"y":100}'
    $r = Invoke-WebRequest "$base/api/act" -Method POST -ContentType "application/json" -Body $body -UseBasicParsing
    $j = $r.Content | ConvertFrom-Json
    if (-not $j.success) { throw "move failed: $($j.message)" }
}

Test-Endpoint "voice-act dry run" {
    $body = '{"command":"read screen","execute":false}'
    $r = Invoke-WebRequest "$base/api/voice-act" -Method POST -ContentType "application/json" -Body $body -UseBasicParsing
    $j = $r.Content | ConvertFrom-Json
    if (-not $j.success -or $j.action -ne "read_screen") { throw "voice-act dry run failed: $($j.message)" }
}

Write-Host "All smoke tests passed." -ForegroundColor Cyan