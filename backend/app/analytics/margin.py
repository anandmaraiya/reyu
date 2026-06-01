"""Margin estimation aligned with how NSE / Indian brokers actually charge.

Three-tier resolution:

  1. Fyers SPAN endpoint (`span_margin`) — authoritative when authenticated.
     Returns broker-computed SPAN + Exposure for the basket (already nets
     hedges, applies stock-vs-index ratios, etc.).

  2. Payoff-aware fallback — when SPAN call fails or in dry-run we use the
     payoff curve's `max_loss` (bounded-risk shortcut) combined with naked-
     short notional %:
       - long-only basket   → premium debit only
       - defined-risk spread (max_loss finite & bounded)
                            → |max_loss| + net debit, capped at naked sum
       - naked short present → SPAN ≈ 10% × notional (index) / 17% (stock)
                                + Exposure ≈ 3% × notional + premium netted

  3. Per-leg breakdown so the UI can show which legs are eating the margin.

These percentages match Zerodha/Groww quotes within ±20% for index options
near ATM (Jan 2026). The Fyers SPAN endpoint should be preferred whenever
available; the fallback is for offline / pre-trade scenario planning.
"""
from __future__ import annotations

import math
from typing import Any
from fastapi.concurrency import run_in_threadpool
from fyers_apiv3 import fyersModel

from app.config import settings
from app.fyers import client as fy
from app.fyers.symbols import resolve, SymbolInfo

# Naked-short margin as % of underlying notional (lot_size * spot)
SPAN_INDEX = 0.10          # ~10% SPAN for index options
SPAN_STOCK = 0.17          # ~17% SPAN for stock options
EXPOSURE_PCT = 0.03        # ~3% exposure margin
FUTURE_MARGIN_PCT = 0.13   # ~13% for futures


async def _fyers_span(legs: list[dict]) -> dict[str, Any] | None:
    token = await fy.get_access_token()
    if not token:
        return None
    m = fyersModel.FyersModel(
        client_id=settings.fyers_app_id, token=token, is_async=False, log_path=""
    )
    payload = {"data": [{
        "symbol": l["symbol"],
        "qty": l["qty"],
        "side": 1 if l["action"] == "BUY" else -1,
        "type": 2,
        "productType": l.get("product", "INTRADAY"),
        "limitPrice": l.get("price", 0),
        "stopLoss": 0, "stopPrice": 0, "takeProfit": 0,
    } for l in legs]}
    try:
        return await run_in_threadpool(m.span_margin, data=payload)
    except Exception as e:
        return {"_error": str(e)}


def _is_index_underlying(underlying: str | None) -> bool:
    if not underlying:
        return False
    return underlying.upper() in {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
                                  "SENSEX", "BANKEX", "NIFTYNXT50"}


async def _per_leg_unhedged(legs: list[dict], spot_lookup: dict[str, float]) -> list[dict]:
    """Margin each leg would require if traded in isolation."""
    out = []
    for l in legs:
        info: SymbolInfo = await resolve(l["symbol"])
        spot = spot_lookup.get(info.underlying or l["symbol"], 0)
        lot = max(info.lot_size, 1)
        qty = l["qty"]
        premium = (l.get("price", 0) or 0) * qty
        notional = spot * qty if spot else (info.strike or 0) * qty

        margin = 0.0
        kind = info.instrument
        if kind == "OPTION":
            if l["action"] == "BUY":
                margin = premium                                # premium only
            else:
                span_pct = SPAN_INDEX if _is_index_underlying(info.underlying) else SPAN_STOCK
                margin = notional * (span_pct + EXPOSURE_PCT) - premium  # received premium reduces requirement
                margin = max(margin, notional * 0.05)           # floor
        elif kind == "FUTURE":
            margin = notional * FUTURE_MARGIN_PCT
        elif kind == "EQUITY":
            margin = premium if l.get("product", "CNC") == "CNC" else premium * 0.20

        out.append({
            "symbol": l["symbol"],
            "instrument": kind,
            "lots": qty // lot if lot > 1 else qty,
            "premium": round(premium, 2),
            "notional": round(notional, 2),
            "margin_unhedged": round(max(margin, 0), 2),
        })
    return out


def _has_naked_short(legs: list[dict]) -> bool:
    """A short option/future is naked if no opposing long leg of same kind/expiry hedges it.
    Simple proxy: there's a SELL option leg with no BUY option leg of the same option_type."""
    has_short_ce = any(l["action"] == "SELL" and l.get("option_type") == "CE" for l in legs)
    has_short_pe = any(l["action"] == "SELL" and l.get("option_type") == "PE" for l in legs)
    has_long_ce = any(l["action"] == "BUY" and l.get("option_type") == "CE" for l in legs)
    has_long_pe = any(l["action"] == "BUY" and l.get("option_type") == "PE" for l in legs)
    short_future = any(l["action"] == "SELL" and l.get("instrument") == "FUTURE" for l in legs)
    return (has_short_ce and not has_long_ce) or (has_short_pe and not has_long_pe) or short_future


async def estimate(
    legs: list[dict],
    payoff: dict | None = None,
    spot: float | None = None,
) -> dict[str, Any]:
    """legs = [{symbol, action, qty, price, instrument?, option_type?, strike?}]
    If `payoff` is provided we use its `max_loss` to detect defined-risk shortcuts.
    """
    if not legs:
        return {"total": 0, "per_leg": [], "source": "empty"}

    # 1. Try Fyers SPAN
    resp = await _fyers_span(legs)
    if resp and isinstance(resp, dict) and "_error" not in resp:
        data = resp.get("data", resp) if isinstance(resp, dict) else {}
        total = (
            data.get("total") or data.get("margin_total")
            or data.get("total_requirement") or 0
        )
        if total:
            return {
                "total": round(float(total), 2),
                "span": data.get("span_margin") or data.get("span"),
                "exposure": data.get("exposure_margin") or data.get("exposure"),
                "per_leg": data.get("margin_avail") or data.get("legs") or [],
                "source": "fyers",
            }

    # 2. Payoff-aware fallback
    spot_lookup: dict[str, float] = {}
    if spot:
        for l in legs:
            info = await resolve(l["symbol"])
            if info.underlying:
                spot_lookup[info.underlying] = spot
            spot_lookup[l["symbol"]] = spot

    per_leg = await _per_leg_unhedged(legs, spot_lookup)
    unhedged_total = sum(p["margin_unhedged"] for p in per_leg)
    long_only = all(l["action"] == "BUY" for l in legs)
    naked_short = _has_naked_short(legs)

    net_debit = sum(
        (1 if l["action"] == "BUY" else -1) * (l.get("price", 0) or 0) * l["qty"]
        for l in legs
    )

    if long_only:
        total = max(net_debit, 0)
        category = "long-only (premium only)"
    elif not naked_short and payoff and math.isfinite(payoff.get("max_loss", 0)):
        # Defined-risk spread: brokers charge ~|max_loss| + net debit
        spread_margin = abs(payoff["max_loss"]) + max(net_debit, 0)
        total = min(spread_margin, unhedged_total)
        category = "defined-risk spread"
    else:
        # Naked short or undefined risk → full unhedged SPAN+Exposure stack
        total = unhedged_total
        category = "naked short / undefined risk"

    return {
        "total": round(total, 2),
        "category": category,
        "per_leg": per_leg,
        "premium_debit": round(net_debit, 2),
        "source": "estimate",
    }
