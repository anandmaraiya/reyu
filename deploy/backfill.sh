#!/usr/bin/env bash
# =============================================================================
# Reyu.ai — Initial Data Backfill Script
# Run once on a fresh VM after containers are up.
#
# Usage:
#   chmod +x deploy/backfill.sh
#   ./deploy/backfill.sh [API_URL] [FYERS_TOKEN] [TOKEN_SECRET]
#
# Defaults:
#   API_URL       = http://localhost:8000
#   FYERS_TOKEN   = (empty — Fyers steps skipped)
#   TOKEN_SECRET  = from REYU_TOKEN_SECRET env var
#
# Examples:
#   ./deploy/backfill.sh                                       # Bhavcopy only (no Fyers)
#   ./deploy/backfill.sh http://localhost:8000 "XYZ.token123"  # Full backfill
# =============================================================================
set -euo pipefail

API="${1:-http://localhost:8000}"
FYERS_TOKEN="${2:-}"
TOKEN_SECRET="${3:-${REYU_TOKEN_SECRET:-}}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*"; }

# ── 0. Health check ───────────────────────────────────────────────────────────
log "Checking backend health..."
for i in {1..12}; do
  if curl -sf "${API}/api/health" > /dev/null 2>&1; then
    log "Backend is up ✓"
    break
  fi
  if [ "$i" -eq 12 ]; then
    err "Backend not responding after 60s. Is docker compose running?"
    exit 1
  fi
  echo "  waiting... ($i/12)"
  sleep 5
done

# ── 1. Inject Fyers token (if provided) ───────────────────────────────────────
if [ -n "$FYERS_TOKEN" ]; then
  log "Injecting Fyers access token..."
  BODY="{\"access_token\":\"${FYERS_TOKEN}\",\"secret\":\"${TOKEN_SECRET}\"}"
  RESP=$(curl -sf -X POST "${API}/api/auth/set-token" \
    -H "Content-Type: application/json" \
    -d "$BODY")
  log "Token injected: $RESP"
else
  warn "No Fyers token provided — Fyers-dependent steps (option_contract_1m, tick_1m) will be skipped."
  warn "Re-run with: ./deploy/backfill.sh ${API} \"YOUR_FYERS_TOKEN\""
fi

# ── 2. Check Fyers auth status ────────────────────────────────────────────────
FYERS_AUTH=$(curl -sf "${API}/api/auth/status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('authenticated','false'))" 2>/dev/null || echo "false")
log "Fyers authenticated: ${FYERS_AUTH}"

# ── 3. Trigger full backfill ──────────────────────────────────────────────────
log "Queuing full backfill (3 years Bhavcopy + 100 days options)..."
RESP=$(curl -sf -X POST \
  "${API}/api/data/full-backfill?bhavcopy_years=3&option_days=100&strikes_around_atm=10")
log "Queued: $RESP"

echo ""
log "Backfill running in background. Monitor progress with:"
echo "  curl ${API}/api/data/status | python3 -m json.tool"
echo ""

# ── 4. Poll status every 30s for 10 minutes ───────────────────────────────────
log "Polling /api/data/status every 30s (Ctrl+C to stop watching)..."
for i in {1..20}; do
  sleep 30
  STATUS=$(curl -sf "${API}/api/data/status" 2>/dev/null || echo "{}")
  BHAV_ROWS=$(echo "$STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('bhavcopy',{}).get('rows',0))" 2>/dev/null || echo "?")
  OC_ROWS=$(echo "$STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('option_candles_1m',{}).get('rows',0))" 2>/dev/null || echo "?")
  TICK_ROWS=$(echo "$STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('spot_candles_1m',{}).get('rows',0))" 2>/dev/null || echo "?")
  log "Progress [${i}/20] | Bhavcopy: ${BHAV_ROWS} rows | Option 1m: ${OC_ROWS} rows | Spot 1m: ${TICK_ROWS} rows"
done

echo ""
log "Final status:"
curl -sf "${API}/api/data/status" | python3 -m json.tool
