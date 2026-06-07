# start_market_day.ps1 — one-button Monday-morning prep.
#
# Run this any time before 09:15 IST on a trading day. It:
#   1. Boots Docker containers (postgres + redis + backend)
#   2. Verifies Fyers auth (warns if you need to re-login at /login)
#   3. Verifies tier-1 polling started + snapshot pipeline writing
#   4. Acquires the wake-lock until 15:35 IST so the laptop can't sleep
#
# Usage:
#   .\scripts\start_market_day.ps1
#
# If you want it to run unattended from boot, schedule it via Windows
# Task Scheduler with trigger "At log on" and action "powershell.exe
# -ExecutionPolicy Bypass -File <full path>\start_market_day.ps1".

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host ""
Write-Host "  Reyu market-day startup  " -BackgroundColor DarkBlue -ForegroundColor White
Write-Host ""

# 1. Containers
Write-Host "[1/4] Bringing up Docker containers..."
Push-Location $root
try {
    docker compose up -d
} finally {
    Pop-Location
}

# 2. Wait for backend health
Write-Host "[2/4] Waiting for backend health..."
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-RestMethod 'http://localhost:8000/api/health' -TimeoutSec 3
        if ($r.status -eq 'ok') { $healthy = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $healthy) {
    Write-Host "  Backend did not come up in 60 s. Check 'docker compose logs backend'." -ForegroundColor Red
    exit 1
}
Write-Host "  Backend healthy." -ForegroundColor Green

# 3. Fyers auth check
Write-Host "[3/4] Checking Fyers auth..."
try {
    $auth = Invoke-RestMethod 'http://localhost:8000/api/auth/status' -TimeoutSec 5
    if (-not $auth.authenticated) {
        Write-Host "  Fyers token expired or absent." -ForegroundColor Yellow
        Write-Host "  -> Open http://localhost:5173/login and click 'Connect Fyers' BEFORE 09:15 IST."
        Write-Host "     Snapshot pipeline will fall back to mock data otherwise."
    } else {
        Write-Host "  Fyers authenticated." -ForegroundColor Green
    }
} catch {
    Write-Host "  Could not reach auth endpoint: $($_.Exception.Message)" -ForegroundColor Red
}

# 4. Acquire wake-lock until 15:35 IST
Write-Host "[4/4] Acquiring wake-lock until 15:35 IST..."
Write-Host ""
Write-Host "  Press Ctrl-C to release the lock manually." -ForegroundColor Cyan
Write-Host ""
& "$PSScriptRoot\keep_awake.ps1" -ReleaseAt "15:35" -Verbose
