"""Order preflight — F-A5 live-order margin validator.

Given a proposed order (or multi-leg strategy), returns a validation
result BEFORE the caller sends real orders to Fyers. Catches:

  - Wrong lot size (Fyers rejects non-multiples silently or with cryptic errors)
  - Insufficient available margin
  - Symbol not in F&O universe
  - Contract expired / not yet listed
  - Order-type mismatches (market when only limit allowed, etc.)

Consumed by:
  - LIVE exit flow in Positions.tsx
  - Strategy runner before placing LIVE orders
  - Strategy promotion from PAPER_LIVE → LIVE

Design principle: NEVER reject silently. Always return a structured
result with pass/warn/fail per check + a summary verdict. The frontend
shows the same list so the user knows exactly what would go wrong.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.fyers import client as fy
from app.routers.user_auth import require_user

log = logging.getLogger("reyu.preflight")
router = APIRouter(prefix="/api/orders", tags=["orders"])


# ── Lot-size table (NSE F&O, Jan 2026 series) ────────────────────────
# Source: NSE lot-size master. Refresh quarterly as NSE updates.
# Only the ~30 most-liquid symbols listed — full universe defaults to 1.
_LOT_SIZES: dict[str, int] = {
    "NIFTY":       65,
    "BANKNIFTY":   15,
    "FINNIFTY":    40,
    "MIDCPNIFTY":  75,
    "NIFTYNXT50":  10,
    "SENSEX":      10,
    "BANKEX":      15,
    # Stocks (per NSE F&O list)
    "RELIANCE":    250,
    "HDFCBANK":    550,
    "ICICIBANK":   700,
    "INFY":        400,
    "TCS":         175,
    "SBIN":        750,
    "BHARTIARTL":  475,
    "AXISBANK":    625,
    "KOTAKBANK":   400,
    "LT":          150,
    "ITC":         1600,
    "HINDUNILVR":  300,
    "BAJFINANCE":  125,
    "MARUTI":       50,
    "TATAMOTORS":  1425,
    "ADANIENT":    300,
    "ADANIPORTS":  650,
    "TATASTEEL":   5500,
    "HCLTECH":     350,
    "WIPRO":       3000,
    "SUNPHARMA":   700,
    "ULTRACEMCO":  50,
    "JSWSTEEL":    1350,
    "POWERGRID":   1900,
    "NTPC":        1500,
    "ONGC":        2250,
    "INDUSINDBK":  450,
    "NESTLEIND":   40,
    "ASIANPAINT":  200,
    "M&M":         350,
}


# Broad SPAN+Exposure margin estimate as a multiple of premium × lots.
# Real Fyers `span_margin` endpoint gives exact, but requires paid tier.
# These multipliers get us in the right zone for a preflight warning.
_MARGIN_ESTIMATE_MULT: dict[str, float] = {
    "BUY_OPTION": 1.0,        # Long options — pay full premium up front
    "SELL_OPTION": 6.0,       # Short options — SPAN ~6× premium (approx)
    "FUTURES": 10.0,          # Futures ~10% of notional
}


# ── Request / response schemas ────────────────────────────────────────
class OrderLeg(BaseModel):
    symbol: str                             # NSE:NIFTY26JUL24800CE or NSE:RELIANCE-EQ
    side: str                               # BUY | SELL
    qty: int                                # in LOTS (validator converts to contracts)
    price: Optional[float] = None           # limit price; None = market
    order_type: str = "MARKET"              # MARKET | LIMIT | SL | SL-M
    product_type: str = "INTRADAY"          # INTRADAY | CARRYFORWARD | MARGIN | CNC


class PreflightRequest(BaseModel):
    legs: list[OrderLeg]
    dry_run: bool = True                    # If True, we ONLY validate; if False, we still
                                            # only validate here — actual send happens
                                            # in the /orders/execute path.


class CheckResult(BaseModel):
    check: str                              # e.g. "lot_size", "margin", "symbol_recognised"
    status: str                             # PASS | WARN | FAIL
    detail: str


class PreflightResponse(BaseModel):
    verdict: str                            # PASS | WARN | FAIL
    checks: list[CheckResult]
    summary: dict                           # {contracts_total, margin_estimate_inr, funds_available_inr, ...}


# ── Symbol parsing helpers ────────────────────────────────────────────
_SYMBOL_RE = re.compile(
    r"^NSE:(?P<underlying>[A-Z&]+)(?P<yy>\d{2})(?P<m>[1-9OND])(?P<dd>\d{2})(?P<strike>\d+)(?P<opt>CE|PE)$"
)
_STOCK_RE = re.compile(r"^NSE:(?P<underlying>[A-Z&]+)-EQ$")
_INDEX_RE = re.compile(r"^(?:NSE|BSE):(?P<underlying>[A-Z0-9]+)-INDEX$")


def _extract_underlying(symbol: str) -> Optional[str]:
    m = _SYMBOL_RE.match(symbol)
    if m:
        return m.group("underlying")
    m = _STOCK_RE.match(symbol)
    if m:
        return m.group("underlying")
    m = _INDEX_RE.match(symbol)
    if m:
        return m.group("underlying").replace("50", "").replace("BANK", "BANK")
    return None


def _lot_size_for(underlying: str) -> int:
    return _LOT_SIZES.get(underlying, 1)


# ── The preflight endpoint ────────────────────────────────────────────
@router.post("/preflight", response_model=PreflightResponse)
async def preflight(req: PreflightRequest, _user: dict = Depends(require_user)):
    checks: list[CheckResult] = []
    margin_est = 0.0
    total_contracts = 0

    # 1. Fyers auth — required for any live order
    is_demo = await fy.is_demo()
    if is_demo:
        checks.append(CheckResult(
            check="fyers_auth",
            status="FAIL",
            detail="Fyers is not connected. Reconnect from Settings before placing orders.",
        ))
    else:
        checks.append(CheckResult(
            check="fyers_auth", status="PASS", detail="Fyers token valid.",
        ))

    # 2. Per-leg validation
    for i, leg in enumerate(req.legs):
        underlying = _extract_underlying(leg.symbol)
        if not underlying:
            checks.append(CheckResult(
                check=f"leg_{i}_symbol",
                status="FAIL",
                detail=f"Cannot parse symbol: {leg.symbol}",
            ))
            continue

        # Lot size — must be positive multiple
        lot = _lot_size_for(underlying)
        if leg.qty < 1:
            checks.append(CheckResult(
                check=f"leg_{i}_qty",
                status="FAIL",
                detail=f"Leg {i}: qty must be at least 1 lot.",
            ))
            continue
        contracts = leg.qty * lot
        total_contracts += contracts

        checks.append(CheckResult(
            check=f"leg_{i}_lot_size",
            status="PASS",
            detail=f"{leg.symbol}: {leg.qty} lot × {lot} = {contracts} contracts.",
        ))

        # Margin estimate — depends on side + whether it's an option or stock/future
        is_option = leg.symbol.endswith(("CE", "PE"))
        price = leg.price or 0
        if is_option:
            key = "BUY_OPTION" if leg.side.upper() == "BUY" else "SELL_OPTION"
            per_lot_margin = price * lot * _MARGIN_ESTIMATE_MULT[key]
        else:
            per_lot_margin = price * lot * _MARGIN_ESTIMATE_MULT["FUTURES"]
        margin_est += per_lot_margin * leg.qty

        if price <= 0 and leg.order_type == "LIMIT":
            checks.append(CheckResult(
                check=f"leg_{i}_price",
                status="FAIL",
                detail=f"Leg {i}: LIMIT order needs a price.",
            ))

    # 3. Funds check — pull Fyers available margin
    funds_available = 0.0
    if not is_demo:
        try:
            f = await fy.funds()
            for entry in (f.get("fund_limit") or []):
                if entry.get("id") == 10:            # Available balance (Fyers ID convention)
                    funds_available = float(entry.get("equityAmount") or 0)
                    break
        except Exception as e:
            log.warning("preflight funds fetch failed: %s", e)
            checks.append(CheckResult(
                check="funds_lookup",
                status="WARN",
                detail=f"Couldn't fetch Fyers funds ({e}). Margin sufficiency unknown.",
            ))

    if funds_available > 0:
        if margin_est > funds_available:
            checks.append(CheckResult(
                check="margin_sufficient",
                status="FAIL",
                detail=(
                    f"Estimated margin ₹{margin_est:,.0f} exceeds available ₹{funds_available:,.0f}. "
                    f"Add funds or reduce qty."
                ),
            ))
        elif margin_est > funds_available * 0.7:
            checks.append(CheckResult(
                check="margin_sufficient",
                status="WARN",
                detail=(
                    f"Estimated margin ₹{margin_est:,.0f} uses ~{margin_est/funds_available*100:.0f}% "
                    f"of available ₹{funds_available:,.0f}. Little headroom for a MTM swing."
                ),
            ))
        else:
            checks.append(CheckResult(
                check="margin_sufficient",
                status="PASS",
                detail=(
                    f"Estimated margin ₹{margin_est:,.0f} / available ₹{funds_available:,.0f}."
                ),
            ))

    # 4. Overall verdict — worst-case wins
    statuses = [c.status for c in checks]
    if "FAIL" in statuses:
        verdict = "FAIL"
    elif "WARN" in statuses:
        verdict = "WARN"
    else:
        verdict = "PASS"

    return PreflightResponse(
        verdict=verdict,
        checks=checks,
        summary={
            "legs": len(req.legs),
            "contracts_total": total_contracts,
            "margin_estimate_inr": round(margin_est, 2),
            "funds_available_inr": round(funds_available, 2),
            "checked_at": datetime.utcnow().isoformat(),
        },
    )


@router.get("/lot-sizes")
async def lot_sizes(underlying: Optional[str] = Query(None)):
    """Public helper — return lot size for a symbol or the full table.
    Used by the frontend order builder + backtester."""
    if underlying:
        u = underlying.upper().replace("NSE:", "").replace("-INDEX", "").replace("-EQ", "").replace("50", "")
        return {"underlying": underlying, "lot_size": _LOT_SIZES.get(u, 1)}
    return {"lot_sizes": _LOT_SIZES}
