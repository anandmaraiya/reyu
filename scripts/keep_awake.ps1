# keep_awake.ps1 - Windows sleep / monitor-blank lock for Reyu market hours.
#
# Holds Win32 SetThreadExecutionState so the system + display stay on
# regardless of power-plan settings. Releases automatically on exit.
#
# Usage:
#   .\scripts\keep_awake.ps1                       # run until Ctrl-C
#   .\scripts\keep_awake.ps1 -ReleaseAt "15:35"   # auto-release at HH:mm

param(
    [string]$ReleaseAt = "",
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"

$signature = @'
using System;
using System.Runtime.InteropServices;
public static class Power {
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
'@
Add-Type -TypeDefinition $signature -Language CSharp

# PS 5.1 parses 0x80000000 as signed Int32 (-2147483648) which can't cast
# to UInt32. Use the decimal value via long-typed literal instead.
$ES_CONTINUOUS       = [System.UInt32]2147483648  # 0x80000000
$ES_SYSTEM_REQUIRED  = [System.UInt32]1
$ES_DISPLAY_REQUIRED = [System.UInt32]2

$flags = [System.UInt32]($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED -bor $ES_DISPLAY_REQUIRED)
[Power]::SetThreadExecutionState($flags) | Out-Null

$start = Get-Date
Write-Host ""
Write-Host "  Reyu wake-lock active  " -BackgroundColor DarkGreen -ForegroundColor White
Write-Host "  System + display stay on. Close this window or Ctrl-C to release."
Write-Host ("  Started: {0}" -f $start)
if ($ReleaseAt) {
    Write-Host ("  Will auto-release at: {0} local" -f $ReleaseAt)
}
Write-Host ""

$releaseTime = $null
if ($ReleaseAt) {
    $today = Get-Date -Hour 0 -Minute 0 -Second 0
    $parts = $ReleaseAt -split ":"
    $releaseTime = $today.AddHours([int]$parts[0]).AddMinutes([int]$parts[1])
    if ($releaseTime -lt (Get-Date)) {
        $releaseTime = $releaseTime.AddDays(1)
    }
}

try {
    while ($true) {
        [Power]::SetThreadExecutionState($flags) | Out-Null
        $now = Get-Date
        if ($Verbose) {
            $elapsed = [int]($now - $start).TotalMinutes
            $nowStr = $now.ToString("HH:mm:ss")
            Write-Host ("  Awake for {0} min  (now {1})" -f $elapsed, $nowStr)
        }
        if ($releaseTime -and (Get-Date) -ge $releaseTime) {
            Write-Host ""
            Write-Host "  Reached release time - releasing lock." -ForegroundColor Yellow
            break
        }
        Start-Sleep -Seconds 60
    }
}
finally {
    [Power]::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null
    Write-Host ""
    Write-Host "  Wake-lock released. System may now sleep on its own." -ForegroundColor Cyan
}
