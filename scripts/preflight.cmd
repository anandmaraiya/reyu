@echo off
REM Wrapper for preflight.ps1 — easier to run from cmd or Explorer.
REM Usage: preflight.cmd  [args passed to preflight.ps1]
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0preflight.ps1" %*
