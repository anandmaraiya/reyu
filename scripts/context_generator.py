#!/usr/bin/env python3
"""
AI Context Generator
Scans your codebase and generates token-efficient AI documentation.
Run manually or wire to git hook / CI.

Usage:
  python scripts/context_generator.py               # full regeneration
  python scripts/context_generator.py --diff-only   # only regen if main changed
  python scripts/context_generator.py --dry-run     # print what would be scanned
"""

import os
import sys
import json
import argparse
import subprocess
import textwrap
from pathlib import Path
from datetime import datetime

import httpx  # pip install httpx

# ── Config ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent          # repo root
BACKEND_DIR  = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
AI_CONTEXT_DIR = ROOT / "ai-context"
CLAUDE_MD   = ROOT / "CLAUDE.md"
README_MD   = ROOT / "README.md"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-20250514"

# Extensions to scan per layer
BACKEND_EXTS  = {".py", ".yaml", ".yml", ".toml", ".env.example", ".sql"}
FRONTEND_EXTS = {".ts", ".tsx", ".js", ".jsx", ".json", ".css", ".scss"}

# Files/dirs to always skip
SKIP_DIRS  = {"node_modules", "__pycache__", ".git", ".venv", "venv",
              "dist", "build", ".next", ".cache", "coverage", "htmlcov"}
SKIP_FILES = {".env", ".env.local", ".env.production", "package-lock.json",
              "yarn.lock", "poetry.lock", "uv.lock"}

MAX_FILE_BYTES = 60_000   # skip files larger than this (binary / generated)
MAX_TOKENS_PER_LAYER = 30_000  # cap sent to Claude per layer

# ── Helpers ───────────────────────────────────────────────────────────────────

def git_changed_files_since_last_push() -> list[str]:
    """Return list of files changed on main since previous push."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            capture_output=True, text=True, cwd=ROOT
        )
        return result.stdout.strip().splitlines()
    except Exception:
        return []


def collect_files(directory: Path, extensions: set[str]) -> list[Path]:
    """Recursively collect files with given extensions, respecting skip lists."""
    files = []
    if not directory.exists():
        return files
    for path in directory.rglob("*"):
        if any(skip in path.parts for skip in SKIP_DIRS):
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix not in extensions:
            continue
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        files.append(path)
    return sorted(files)


def read_file_safe(path: Path) -> str:
    """Read file content, return empty string on error."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def build_layer_digest(directory: Path, extensions: set[str], label: str) -> str:
    """
    Build a compact digest of a layer's codebase.
    Format: <filepath>\n```\n<content>\n```\n
    Truncated to MAX_TOKENS_PER_LAYER chars.
    """
    files = collect_files(directory, extensions)
    parts = [f"## {label} layer — {len(files)} files\n"]
    total_chars = 0

    for f in files:
        rel = f.relative_to(ROOT)
        content = read_file_safe(f)
        snippet = content[:3000]  # first 3k chars per file
        entry = f"\n### {rel}\n```\n{snippet}\n```\n"
        if total_chars + len(entry) > MAX_TOKENS_PER_LAYER:
            parts.append(f"\n... (truncated — {len(files) - files.index(f)} files omitted)\n")
            break
        parts.append(entry)
        total_chars += len(entry)

    return "".join(parts)


def call_claude(system_prompt: str, user_content: str) -> str:
    """Call Claude API and return response text."""
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY not set")

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_content}],
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"]


# ── Scanners ──────────────────────────────────────────────────────────────────

def scan_backend() -> dict:
    """Extract structured info from backend layer."""
    digest = build_layer_digest(BACKEND_DIR, BACKEND_EXTS, "Backend")

    # Quick structural scan without Claude (fast, zero cost)
    routes, models, schemas = [], [], []
    for f in collect_files(BACKEND_DIR, {".py"}):
        content = read_file_safe(f)
        rel = str(f.relative_to(ROOT))
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(("@router.", "@app.")):
                routes.append(f"{rel}: {stripped}")
            elif stripped.startswith("class ") and "Model" in stripped:
                models.append(f"{rel}: {stripped.split(':')[0]}")
            elif stripped.startswith("class ") and "Schema" in stripped:
                schemas.append(f"{rel}: {stripped.split(':')[0]}")

    return {
        "digest": digest,
        "routes_found": routes[:50],
        "models_found": models[:30],
        "schemas_found": schemas[:30],
    }


def scan_frontend() -> dict:
    """Extract structured info from frontend layer."""
    digest = build_layer_digest(FRONTEND_DIR, FRONTEND_EXTS, "Frontend")

    components, pages, hooks, stores = [], [], [], []
    for f in collect_files(FRONTEND_DIR, {".tsx", ".ts", ".jsx", ".js"}):
        rel = str(f.relative_to(ROOT))
        name = f.stem
        if "page" in rel.lower() or "Page" in name:
            pages.append(rel)
        elif "hook" in rel.lower() or name.startswith("use"):
            hooks.append(rel)
        elif "store" in rel.lower() or "slice" in rel.lower():
            stores.append(rel)
        elif f.suffix in {".tsx", ".jsx"}:
            components.append(rel)

    return {
        "digest": digest,
        "components": components[:40],
        "pages": pages[:20],
        "hooks": hooks[:20],
        "stores": stores[:10],
    }


def scan_infra() -> dict:
    """Extract env vars, DB config, docker, CI."""
    info = {}

    # .env.example
    env_example = ROOT / ".env.example"
    if env_example.exists():
        info["env_vars"] = read_file_safe(env_example)

    # docker-compose
    for name in ["docker-compose.yml", "docker-compose.yaml"]:
        dc = ROOT / name
        if dc.exists():
            info["docker_compose"] = read_file_safe(dc)[:3000]
            break

    # pyproject / package.json deps
    pyproject = ROOT / "pyproject.toml"
    if pyproject.exists():
        info["backend_deps"] = read_file_safe(pyproject)[:2000]

    pkg = FRONTEND_DIR / "package.json"
    if pkg.exists():
        try:
            pkg_data = json.loads(read_file_safe(pkg))
            info["frontend_deps"] = {
                "dependencies": list(pkg_data.get("dependencies", {}).keys()),
                "devDependencies": list(pkg_data.get("devDependencies", {}).keys()),
            }
        except json.JSONDecodeError:
            pass

    return info


# ── Generators ────────────────────────────────────────────────────────────────

CLAUDE_MD_SYSTEM = textwrap.dedent("""
You are a senior software architect generating CLAUDE.md — a single-file AI working context document.
Rules:
- Target 600-900 tokens. Every word earns its place.
- Structure with H2 sections: Project, Stack, Architecture, Key Patterns, Dev Conventions, Active Work, Never Touch
- Use bullet points for lists, inline code for symbols, file paths, function names
- "Active Work" = what appears to be WIP / in-flight based on TODO comments, recent files, incomplete patterns
- "Never Touch" = config files, generated files, secrets, migration files that should never be hand-edited
- No fluff, no marketing language, no "this is a great project" — pure engineering signal
- Write as if briefing a senior engineer who has never seen this repo but needs to make a PR in 1 hour
""").strip()

README_SYSTEM = textwrap.dedent("""
You are a senior software architect generating README.md for a software project.
Rules:
- Target 400-600 tokens. Human-readable but also AI-parseable.
- Structure: Project overview (2-3 sentences), Tech stack table, Folder structure, Quick start (numbered steps), Environment variables table, API overview (endpoints table), Contributing notes
- Use markdown tables for stack and env vars
- Quick start must be runnable: actual commands, not pseudocode
- No badges, no screenshots section, no license boilerplate
""").strip()

AI_CONTEXT_SYSTEM = textwrap.dedent("""
You are generating a technical deep-dive document for AI assistants.
Rules:
- Be extremely precise and dense. No prose padding.
- For Backend: list every route (METHOD /path → handler → description), every model (fields + types), every schema
- For Frontend: list every page (path → component), every shared component (props interface), every API call made
- Use markdown tables wherever a table fits better than a list
- Target 800-1200 tokens per layer doc
""").strip()


def generate_claude_md(backend: dict, frontend: dict, infra: dict) -> str:
    user_content = f"""
Backend routes: {json.dumps(backend['routes_found'], indent=2)}
Backend models: {json.dumps(backend['models_found'], indent=2)}
Frontend pages: {json.dumps(frontend['pages'], indent=2)}
Frontend stores: {json.dumps(frontend['stores'], indent=2)}
Frontend hooks: {json.dumps(frontend['hooks'], indent=2)}
Infra/env: {json.dumps({k: v for k, v in infra.items() if k != 'docker_compose'}, indent=2)}

Backend code digest (sampled):
{backend['digest'][:8000]}

Frontend code digest (sampled):
{frontend['digest'][:6000]}
"""
    result = call_claude(CLAUDE_MD_SYSTEM, user_content)
    return f"<!-- Auto-generated by context_generator.py on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} -->\n\n{result}"


def generate_readme(backend: dict, frontend: dict, infra: dict) -> str:
    user_content = f"""
Backend routes: {json.dumps(backend['routes_found'][:20], indent=2)}
Backend models: {json.dumps(backend['models_found'][:15], indent=2)}
Frontend pages: {json.dumps(frontend['pages'][:15], indent=2)}
Infra info: {json.dumps(infra, indent=2)[:3000]}

Code samples:
{backend['digest'][:4000]}
{frontend['digest'][:3000]}
"""
    result = call_claude(README_SYSTEM, user_content)
    return f"<!-- Auto-generated by context_generator.py on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} -->\n\n{result}"


def generate_backend_context(backend: dict) -> str:
    user_content = f"""
Routes found: {json.dumps(backend['routes_found'], indent=2)}
Models found: {json.dumps(backend['models_found'], indent=2)}
Schemas found: {json.dumps(backend['schemas_found'], indent=2)}

Full backend digest:
{backend['digest'][:15000]}
"""
    return call_claude(AI_CONTEXT_SYSTEM, f"Generate a BACKEND deep-dive context doc.\n{user_content}")


def generate_frontend_context(frontend: dict) -> str:
    user_content = f"""
Pages: {json.dumps(frontend['pages'], indent=2)}
Components: {json.dumps(frontend['components'][:30], indent=2)}
Hooks: {json.dumps(frontend['hooks'], indent=2)}
Stores: {json.dumps(frontend['stores'], indent=2)}

Full frontend digest:
{frontend['digest'][:12000]}
"""
    return call_claude(AI_CONTEXT_SYSTEM, f"Generate a FRONTEND deep-dive context doc.\n{user_content}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate AI context docs for this repo")
    parser.add_argument("--diff-only", action="store_true",
                        help="Skip generation if no relevant files changed")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print scan summary without calling Claude or writing files")
    parser.add_argument("--no-readme", action="store_true",
                        help="Skip README.md regeneration (keep hand-written readme)")
    args = parser.parse_args()

    # Diff-only guard
    if args.diff_only:
        changed = git_changed_files_since_last_push()
        skip_patterns = {"ai-context/", "CLAUDE.md", "README.md"}
        relevant = [f for f in changed if not any(p in f for p in skip_patterns)]
        if not relevant:
            print("⏭  No relevant code changes detected. Skipping context regeneration.")
            sys.exit(0)
        print(f"📂 {len(relevant)} changed files detected. Regenerating context...")

    print("🔍 Scanning backend...")
    backend = scan_backend()
    print(f"   Found {len(backend['routes_found'])} routes, {len(backend['models_found'])} models")

    print("🔍 Scanning frontend...")
    frontend = scan_frontend()
    print(f"   Found {len(frontend['pages'])} pages, {len(frontend['components'])} components")

    print("🔍 Scanning infra...")
    infra = scan_infra()
    print(f"   Found {len(infra)} infra files")

    if args.dry_run:
        print("\n--- DRY RUN SUMMARY ---")
        print(json.dumps({
            "backend_routes": backend["routes_found"][:5],
            "backend_models": backend["models_found"][:5],
            "frontend_pages": frontend["pages"][:5],
            "infra_keys": list(infra.keys()),
        }, indent=2))
        print("\nWould write: CLAUDE.md, README.md, ai-context/backend.md, ai-context/frontend.md")
        sys.exit(0)

    if not ANTHROPIC_API_KEY:
        print("❌ ANTHROPIC_API_KEY not set. Export it and retry.")
        sys.exit(1)

    AI_CONTEXT_DIR.mkdir(exist_ok=True)

    print("\n🤖 Generating CLAUDE.md...")
    claude_content = generate_claude_md(backend, frontend, infra)
    CLAUDE_MD.write_text(claude_content, encoding="utf-8")
    print(f"   ✅ Written ({len(claude_content)} chars)")

    if not args.no_readme:
        print("🤖 Generating README.md...")
        readme_content = generate_readme(backend, frontend, infra)
        README_MD.write_text(readme_content, encoding="utf-8")
        print(f"   ✅ Written ({len(readme_content)} chars)")

    print("🤖 Generating ai-context/backend.md...")
    backend_doc = generate_backend_context(backend)
    (AI_CONTEXT_DIR / "backend.md").write_text(backend_doc, encoding="utf-8")
    print(f"   ✅ Written ({len(backend_doc)} chars)")

    print("🤖 Generating ai-context/frontend.md...")
    frontend_doc = generate_frontend_context(frontend)
    (AI_CONTEXT_DIR / "frontend.md").write_text(frontend_doc, encoding="utf-8")
    print(f"   ✅ Written ({len(frontend_doc)} chars)")

    print("\n✅ All context files updated.")
    print("   Stage and commit with: git add CLAUDE.md README.md ai-context/ && git commit -m 'docs: update AI context'")


if __name__ == "__main__":
    main()
