# preflight.ps1 - pre-push smoke test for Reyu.
# Run before pushing to catch the breakage classes we've actually hit:
#   * backend down / not yet healthy
#   * AuthMiddleware blocking CORS preflight
#   * Frontend served from wrong port
#   * Docker containers crashed
#
# Exit codes:
#   0 - all green, push is safe
#   1 - one or more checks failed; push aborted
#
# Usage:
#   .\scripts\preflight.ps1                    # full check
#   .\scripts\preflight.ps1 -SkipContainerCheck  # if Docker is not running locally
#   .\scripts\preflight.ps1 -Quiet               # only print failures

param(
    [switch]$SkipContainerCheck,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$failures = @()
$ok = @()

function Pass($msg) {
    $script:ok += $msg
    if (-not $Quiet) { Write-Host ("  OK  {0}" -f $msg) -ForegroundColor Green }
}

function Fail($msg) {
    $script:failures += $msg
    Write-Host ("  FAIL  {0}" -f $msg) -ForegroundColor Red
}

# ── 1. Containers up ───────────────────────────────────────────────
if (-not $SkipContainerCheck) {
    Write-Host "[1/5] Docker containers..." -ForegroundColor Cyan
    try {
        $services = @("backend", "postgres", "redis", "frontend")
        $running = docker compose ps --format "{{.Service}}={{.State}}" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Fail "docker compose not responding (Docker Desktop running?)"
        } else {
            foreach ($svc in $services) {
                $line = $running | Where-Object { $_ -like "$svc=*" } | Select-Object -First 1
                if ($line -and $line -like "*running*") {
                    Pass "container $svc running"
                } else {
                    Fail "container $svc not running (got: $line)"
                }
            }
        }
    } catch {
        Fail "container check failed: $($_.Exception.Message)"
    }
} else {
    Write-Host "[1/5] Skipping container check" -ForegroundColor Yellow
}

# ── 2. Backend health ──────────────────────────────────────────────
Write-Host "[2/5] Backend /api/health..." -ForegroundColor Cyan
try {
    $r = Invoke-RestMethod 'http://localhost:8000/api/health' -TimeoutSec 10
    if ($r.status -eq 'ok') {
        Pass "/api/health -> ok"
    } else {
        Fail "/api/health -> unexpected: $($r.status)"
    }
} catch {
    Fail "/api/health unreachable: $($_.Exception.Message)"
}

# ── 3. CORS preflight on a protected route ─────────────────────────
# This caught the bug where the AuthMiddleware was 401-ing the OPTIONS
# preflight, leaving the browser stuck on every authed page.
Write-Host "[3/5] CORS preflight on /api/strategies..." -ForegroundColor Cyan
try {
    $headers = @{
        'Origin' = 'http://localhost:5173'
        'Access-Control-Request-Method' = 'GET'
        'Access-Control-Request-Headers' = 'authorization'
    }
    $resp = Invoke-WebRequest -Method Options -Uri 'http://localhost:8000/api/strategies' `
        -Headers $headers -TimeoutSec 10 -UseBasicParsing
    if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400) {
        Pass "CORS preflight -> HTTP $($resp.StatusCode)"
        if ($resp.Headers['Access-Control-Allow-Origin']) {
            Pass "Access-Control-Allow-Origin present"
        } else {
            Fail "CORS headers missing on preflight response"
        }
    } else {
        Fail "CORS preflight -> HTTP $($resp.StatusCode) (auth middleware bug?)"
    }
} catch {
    Fail "CORS preflight failed: $($_.Exception.Message)"
}

# ── 4. Frontend reachable ──────────────────────────────────────────
Write-Host "[4/5] Frontend root..." -ForegroundColor Cyan
try {
    $resp = Invoke-WebRequest 'http://localhost:5173/' -TimeoutSec 10 -UseBasicParsing
    if ($resp.StatusCode -ne 200) {
        Fail "frontend -> HTTP $($resp.StatusCode)"
    } elseif ($resp.Content -match 'Reyu') {
        Pass "frontend served, title contains 'Reyu'"
    } else {
        Fail "frontend served but content unexpected (no Reyu in body)"
    }
} catch {
    Fail "frontend unreachable: $($_.Exception.Message)"
}

# ── 5. Strategy router mounted (smoke that we didn't regress) ──────
Write-Host "[5/5] /api/strategies router mounted..." -ForegroundColor Cyan
try {
    # Should respond 401 (unauthenticated) - confirms the route exists
    $r = $null
    try {
        $r = Invoke-WebRequest 'http://localhost:8000/api/strategies' -TimeoutSec 10 -UseBasicParsing
    } catch {
        $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        if ($code -eq 401) {
            Pass "/api/strategies -> 401 (router mounted, auth working)"
        } elseif ($code -eq 404) {
            Fail "/api/strategies -> 404 (router not mounted)"
        } else {
            Fail "/api/strategies -> unexpected HTTP $code"
        }
    }
    if ($r -ne $null) {
        # Got 200 without auth - that would be a security regression
        Fail "/api/strategies returned $($r.StatusCode) WITHOUT auth header (security regression)"
    }
} catch {
    Fail "strategies smoke failed: $($_.Exception.Message)"
}

# ── Summary ────────────────────────────────────────────────────────
Write-Host ""
Write-Host ("Result: {0} passed, {1} failed" -f $ok.Count, $failures.Count) -ForegroundColor $(if ($failures.Count) { 'Red' } else { 'Green' })

if ($failures.Count -gt 0) {
    Write-Host ""
    Write-Host "Failures:" -ForegroundColor Red
    foreach ($f in $failures) { Write-Host "  - $f" -ForegroundColor Red }
    Write-Host ""
    Write-Host "Push BLOCKED. Fix the above and re-run, or push with --no-verify to bypass." -ForegroundColor Yellow
    exit 1
}

Write-Host "All checks green. Push OK." -ForegroundColor Green
exit 0
