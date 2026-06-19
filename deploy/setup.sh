#!/usr/bin/env bash
# Reyu.ai — Linux VM one-shot setup script
# Run as root or with sudo: bash setup.sh
set -euo pipefail

REYU_DIR="${1:-/opt/reyu}"
REPO_URL="${REPO_URL:-}"   # set to your git remote if cloning, else leave empty

echo "==> [1/6] Installing Docker & Docker Compose..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
fi
if ! docker compose version &>/dev/null; then
    COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep '"tag_name"' | cut -d'"' -f4)
    curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
        -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
fi

echo "==> [2/6] Creating project directory: $REYU_DIR"
mkdir -p "$REYU_DIR"
if [ -n "$REPO_URL" ]; then
    git clone "$REPO_URL" "$REYU_DIR" 2>/dev/null || (cd "$REYU_DIR" && git pull)
fi

echo "==> [3/6] Checking .env..."
if [ ! -f "$REYU_DIR/.env" ]; then
    if [ -f "$REYU_DIR/.env.example" ]; then
        cp "$REYU_DIR/.env.example" "$REYU_DIR/.env"
        echo "    !! Created .env from .env.example — EDIT IT before continuing !!"
        echo "    Edit: nano $REYU_DIR/.env"
        echo ""
        echo "    Minimum required fields:"
        echo "      FYERS_APP_ID, FYERS_SECRET_KEY, JWT_SECRET"
        echo ""
        read -rp "    Press Enter once .env is ready, or Ctrl+C to abort..."
    else
        echo "    ERROR: No .env or .env.example found in $REYU_DIR"
        exit 1
    fi
fi

echo "==> [4/6] Installing systemd service..."
SERVICE_SRC="$REYU_DIR/deploy/reyu.service"
if [ -f "$SERVICE_SRC" ]; then
    # Patch WorkingDirectory in service file to actual path
    sed "s|/opt/reyu|$REYU_DIR|g" "$SERVICE_SRC" > /etc/systemd/system/reyu.service
    systemctl daemon-reload
    systemctl enable reyu.service
    echo "    Service installed: systemctl {start|stop|status} reyu"
else
    echo "    WARNING: deploy/reyu.service not found — skipping systemd install"
fi

echo "==> [5/6] Pulling images & starting containers..."
cd "$REYU_DIR"
docker compose pull --quiet
docker compose up -d --remove-orphans

echo "==> [6/6] Health check..."
sleep 5
if curl -sf http://localhost:8000/api/health > /dev/null; then
    echo "    ✓ Backend healthy"
else
    echo "    ✗ Backend not responding — check: docker compose logs backend"
fi
if curl -sf http://localhost:5173 > /dev/null; then
    echo "    ✓ Frontend up"
else
    echo "    ✗ Frontend not responding — check: docker compose logs frontend"
fi

echo ""
echo "================================================================"
echo "  Reyu.ai is running!"
echo ""
echo "  Frontend:  http://$(hostname -I | awk '{print $1}'):5173"
echo "  Backend:   http://$(hostname -I | awk '{print $1}'):8000"
echo "  API docs:  http://$(hostname -I | awk '{print $1}'):8000/docs"
echo ""
echo "  Fyers token (headless): see docs/fyers-headless-auth.md"
echo "  Logs: docker compose -f $REYU_DIR/docker-compose.yml logs -f"
echo "================================================================"
