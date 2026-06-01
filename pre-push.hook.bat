@echo off
REM .git/hooks/pre-push (Windows batch version)
REM Auto-generates AI context docs before pushing to main.
REM Install: powershell -ExecutionPolicy Bypass -File install-hooks.ps1

setlocal enabledelayedexpansion

for /f %%i in ('git symbolic-ref --short HEAD 2^>nul') do set BRANCH=%%i

set TARGET_BRANCH=main

REM Only run on pushes to main (or master)
if NOT "%BRANCH%"=="main" if NOT "%BRANCH%"=="master" exit /b 0

echo 🤖 Updating AI context docs for %BRANCH% push...

REM Check Python available
where python >nul 2>nul
if %errorlevel% neq 0 (
    where python3 >nul 2>nul
    if !errorlevel! neq 0 (
        echo ⚠️  python not found in PATH - skipping context generation
        exit /b 0
    )
    set PYTHON=python3
) else (
    set PYTHON=python
)

REM Check ANTHROPIC_API_KEY
if "!ANTHROPIC_API_KEY!"=="" (
    echo ⚠️  ANTHROPIC_API_KEY not set - skipping context generation
    echo    Set it in your environment to enable auto-docs.
    exit /b 0
)

REM Get repo root
for /f %%i in ('git rev-parse --show-toplevel') do set REPO_ROOT=%%i

REM Run generator (diff-only = skip if no relevant code changed)
!PYTHON! "%REPO_ROOT%\scripts\context_generator.py" --diff-only

if %errorlevel% neq 0 (
    echo ❌ Context generation failed (exit %errorlevel%). Push aborted.
    echo    Run with: python scripts/context_generator.py --dry-run  to debug
    exit /b 1
)

REM Auto-stage the updated docs if any were changed
git diff --name-only -- "%REPO_ROOT%\CLAUDE.md" "%REPO_ROOT%\README.md" "%REPO_ROOT%\ai-context\" > nul 2>&1

if %errorlevel% equ 0 (
    git add "%REPO_ROOT%\CLAUDE.md" "%REPO_ROOT%\README.md" "%REPO_ROOT%\ai-context\" 2>nul
    git commit -m "docs: auto-update AI context [skip ci]" --no-verify 2>nul
    echo 📄 AI context committed and included in push.
)

exit /b 0
