# ai-context-system

Auto-generate token-efficient AI documentation from your codebase.
Triggered on every push to `main` — keeps `CLAUDE.md`, `README.md`, and `ai-context/` in sync with the code.

## What it generates

| File | Purpose | Target tokens |
|------|---------|--------------|
| `CLAUDE.md` | AI working context — architecture, patterns, conventions, active work | ~700 |
| `README.md` | Human + AI readable project overview with quick start | ~500 |
| `ai-context/backend.md` | Full route map, model fields, schema table | ~1000 |
| `ai-context/frontend.md` | Page map, component props, API calls made | ~900 |

Loading all four gives any AI assistant a complete picture in one context window chunk.

## Install

```bash
# From your repo root:
curl -fsSL https://raw.githubusercontent.com/your-org/ai-context-system/main/install-hooks.sh | bash
# or clone and run locally:
git clone https://github.com/your-org/ai-context-system
cd your-project
bash ../ai-context-system/install-hooks.sh
```

## Manual usage

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Full regeneration
python3 scripts/context_generator.py

# Only regenerate if code changed since last commit
python3 scripts/context_generator.py --diff-only

# Preview what would be scanned (no API calls)
python3 scripts/context_generator.py --dry-run

# Skip README (keep your hand-written one)
python3 scripts/context_generator.py --no-readme
```

## Folder layout expected

```
your-project/
├── backend/          ← Python/FastAPI (or any backend)
├── frontend/         ← React/TypeScript (or any frontend)
├── .env.example      ← Env var declarations
├── docker-compose.yml
└── pyproject.toml / package.json
```

If your structure differs, edit `BACKEND_DIR` / `FRONTEND_DIR` at the top of `scripts/context_generator.py`.

## GitHub Actions

Add `ANTHROPIC_API_KEY` as a repository secret, then the workflow in `.github/workflows/update-ai-context.yml` runs automatically on every push to main.

## Requirements

- Python 3.9+
- `pip install httpx`
- `ANTHROPIC_API_KEY` env var

## Cost estimate

~$0.003–0.008 per regeneration (4 Claude Sonnet calls on a mid-size codebase).
With `--diff-only`, skips regeneration entirely when only non-code files changed.
# reyu
