# keep_awake.ps1 — Windows sleep / monitor-blank lock for Reyu market hours.
#
# What it does:
#   Calls the Win32 SetThreadExecutionState API with ES_CONTINUOUS |
#   ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED. While this process runs,
#   Windows will not sleep, hibernate, or blank the display, regardless
#   of power-plan settings. Releases automatically when you Ctrl-C or
#   close the window.
#
# Usage:
#   # Manual — run any time before 09:15 IST on a trading day:
#   .\scripts\keep_awake.ps1
#
#   # Auto-release at market close (15:30 IST):
#   .\scripts\keep_awake.ps1 -ReleaseAt "15:35"
#
# Why not powercfg /change?
#   powercfg edits the active power plan, which is global + persistent.
#   SetThreadExecutionState is per-process + auto-cleans on exit — much
#   safer to forget about.
#
# This script does NOT require admin rights.

param(
    [string]$ReleaseAt = "",   # HH:mm in local time; empty = run until Ctrl-C
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"

# Win32 API binding
$signature = @'
using System;
using System.Runtime.InteropServices;
public static class Power {
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
'@
Add-Type -TypeDefinition $signature -Language CSharp

[uint32]$ES_CONTINUOUS       = 0x80000000
[uint32]$ES_SYSTEM_REQUIRED  = 0x00000001
[uint32]$ES_DISPLAY_REQUIRED = 0x00000002

$flags = $ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED -bor $ES_DISPLAY_REQUIRED
[Power]::SetThreadExecutionState($flags) | Out-Null

$start = Get-Date
Write-Host ""
Write-Host "  Reyu wake-lock active  " -BackgroundColor DarkGreen -ForegroundColor White
Write-Host "  System + display stay on. Close this window or Ctrl-C to release."
Write-Host "  Started: $start"
if ($ReleaseAt) {
    Write-Host "  Will auto-release at: $ReleaseAt local"
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
        # Re-assert every 30 s in case another app inadvertently cleared
        # the lock (rare but possible if Group Policy resets it).
        [Power]::SetThreadExecutionState($flags) | Out-Null
        $now = Get-Date
        if ($Verbose) {
            $elapsed = [int]($now - $start).TotalMinutes
            Write-Host -NoNewline "`r  Awake for $elapsed min  (now $($now.ToString('HH:mm:ss')))   "
        }
        if ($releaseTime -and (Get-Date) -ge $releaseTime) {
            Write-Host ""
            Write-Host "  Reached release time — releasing lock." -ForegroundColor Yellow
            break
        }
        Start-Sleep -Seconds 30
    }
}
finally {
    # Restore default behaviour — system/display can sleep again
    [Power]::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null
    Write-Host ""
    Write-Host "  Wake-lock released. System may now sleep on its own." -ForegroundColor Cyan
}
