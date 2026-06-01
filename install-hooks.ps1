# install-hooks.ps1
# Run once from your repo root to install everything.
# Usage: powershell -ExecutionPolicy Bypass -File install-hooks.ps1

$ErrorActionPreference = "Stop"

# Check if we're in a git repo
$REPO_ROOT = git rev-parse --show-toplevel 2>$null
if (-not $REPO_ROOT) {
    Write-Host "Not inside a git repo. Run from your project root." -ForegroundColor Red
    exit 1
}

Write-Host "Installing AI context system..." -ForegroundColor Green

# 1. Copy scripts
$scriptsDir = "$REPO_ROOT\scripts"
New-Item -ItemType Directory -Path $scriptsDir -Force | Out-Null

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Copy-Item "$scriptRoot\context_generator.py" "$scriptsDir\" -Force
Write-Host "   scripts/context_generator.py installed" -ForegroundColor Green

# 2. Install git hook (batch version for Windows)
$hookDir = "$REPO_ROOT\.git\hooks"
New-Item -ItemType Directory -Path $hookDir -Force | Out-Null

$hookSource = "$scriptRoot\pre-push.hook.bat"
if (Test-Path $hookSource) {
    Copy-Item $hookSource "$hookDir\pre-push" -Force
    Write-Host "   .git/hooks/pre-push installed" -ForegroundColor Green
} else {
    Write-Host "   Warning: Could not find pre-push.hook.bat" -ForegroundColor Yellow
}

# 3. Install GitHub Actions workflow
$ghDir = "$REPO_ROOT\.github"
if (Test-Path $ghDir) {
    $workflowDir = "$ghDir\workflows"
    New-Item -ItemType Directory -Path $workflowDir -Force | Out-Null
    
    if (Test-Path "$scriptRoot\update-ai-context.yml") {
        Copy-Item "$scriptRoot\update-ai-context.yml" "$workflowDir\" -Force
        Write-Host "   .github/workflows/update-ai-context.yml installed" -ForegroundColor Green
    }
}

# 4. Python deps
Write-Host ""
Write-Host "Installing Python dependencies..." -ForegroundColor Green

try {
    & pip install httpx --quiet 2>$null
    Write-Host "   httpx installed" -ForegroundColor Green
} catch {
    try {
        & pip3 install httpx --quiet 2>$null
        Write-Host "   httpx installed" -ForegroundColor Green
    } catch {
        Write-Host "   Warning: Could not auto-install httpx - run: pip install httpx" -ForegroundColor Yellow
    }
}

# 5. Create .env.example if missing
$envExample = "$REPO_ROOT\.env.example"
if (-not (Test-Path $envExample)) {
    "# Required for AI context generation" | Out-File $envExample -Encoding UTF8
    "ANTHROPIC_API_KEY=sk-ant-..." | Out-File $envExample -Append -Encoding UTF8
    Write-Host "   .env.example created (add ANTHROPIC_API_KEY)" -ForegroundColor Green
}

# 6. .gitignore ai-context generated note
$gitIgnore = "$REPO_ROOT\.gitignore"
if (Test-Path $gitIgnore) {
    $content = Get-Content $gitIgnore -Raw
    if ($content -notmatch "# AI context") {
        "" | Out-File $gitIgnore -Append -Encoding UTF8
        "# AI context - these ARE committed (they are the docs)" | Out-File $gitIgnore -Append -Encoding UTF8
        "# To exclude: uncomment below" | Out-File $gitIgnore -Append -Encoding UTF8
        "# ai-context/" | Out-File $gitIgnore -Append -Encoding UTF8
        Write-Host "   .gitignore updated" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Export your key:   `$env:ANTHROPIC_API_KEY='sk-ant-...'" -ForegroundColor Cyan
Write-Host "  2. Run first gen:     python scripts/context_generator.py" -ForegroundColor Cyan
Write-Host "  3. Commit the docs:   git add CLAUDE.md README.md ai-context/ && git commit -m 'docs: initial AI context'" -ForegroundColor Cyan
Write-Host ""
Write-Host "After that, docs auto-update on every push to main." -ForegroundColor Cyan
