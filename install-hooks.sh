#!/bin/bash
# install-hooks.sh
# Run once from your repo root to install everything.
# Usage: bash install-hooks.sh

set -e

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [[ -z "$REPO_ROOT" ]]; then
  echo "❌ Not inside a git repo. Run from your project root."
  exit 1
fi

echo "🔧 Installing AI context system..."

# ── 1. Copy scripts ────────────────────────────────────────────────────────

mkdir -p "$REPO_ROOT/scripts"
cp "$(dirname "$0")/context_generator.py" "$REPO_ROOT/scripts/"
chmod +x "$REPO_ROOT/scripts/context_generator.py"
echo "   ✅ scripts/context_generator.py installed"

# ── 2. Install git hook ────────────────────────────────────────────────────

HOOK_DIR="$REPO_ROOT/.git/hooks"
mkdir -p "$HOOK_DIR"
cp "$(dirname "$0")/pre-push.hook" "$HOOK_DIR/pre-push"
chmod +x "$HOOK_DIR/pre-push"
echo "   ✅ .git/hooks/pre-push installed"

# ── 3. Install GitHub Actions workflow (optional) ─────────────────────────

if [[ -d "$REPO_ROOT/.github" ]]; then
  mkdir -p "$REPO_ROOT/.github/workflows"
  cp "$(dirname "$0")/update-ai-context.yml" \
     "$REPO_ROOT/.github/workflows/" 2>/dev/null && \
    echo "   ✅ .github/workflows/update-ai-context.yml installed" || \
    echo "   ⚠️  GitHub Actions workflow not found — skipping"
fi

# ── 4. Python deps ────────────────────────────────────────────────────────

echo ""
echo "📦 Installing Python dependencies..."
pip install httpx --quiet 2>/dev/null || \
  pip3 install httpx --quiet 2>/dev/null || \
  echo "   ⚠️  Could not auto-install httpx — run: pip install httpx"

# ── 5. Create .env.example if missing ────────────────────────────────────

ENV_EXAMPLE="$REPO_ROOT/.env.example"
if [[ ! -f "$ENV_EXAMPLE" ]]; then
  echo "# Required for AI context generation" >> "$ENV_EXAMPLE"
  echo "ANTHROPIC_API_KEY=sk-ant-..." >> "$ENV_EXAMPLE"
  echo "   ✅ .env.example created (add ANTHROPIC_API_KEY)"
fi

# ── 6. .gitignore ai-context generated note ──────────────────────────────

GITIGNORE="$REPO_ROOT/.gitignore"
if [[ -f "$GITIGNORE" ]] && ! grep -q "# AI context" "$GITIGNORE"; then
  echo "" >> "$GITIGNORE"
  echo "# AI context — these ARE committed (they are the docs)" >> "$GITIGNORE"
  echo "# To exclude: uncomment below" >> "$GITIGNORE"
  echo "# ai-context/" >> "$GITIGNORE"
  echo "   ✅ .gitignore updated"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Export your key:   export ANTHROPIC_API_KEY=sk-ant-..."
echo "  2. Run first gen:     python3 scripts/context_generator.py"
echo "  3. Commit the docs:   git add CLAUDE.md README.md ai-context/ && git commit -m 'docs: initial AI context'"
echo ""
echo "After that, docs auto-update on every push to main."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
