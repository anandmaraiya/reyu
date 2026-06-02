"""Margin estimation — Fyers v3 multiorder/margin endpoint with robust fallback.

Resolution order:
  1. Live POST to https://api-t1.fyers.in/api/v3/multiorder/margin
     (the official broker SPAN+Exposure calculator). Requires the user to be
     authenticated; basket-aware netting so hedges show the right number.
  2. Conservative SEBI-aligned fallback when offline / pre-auth:
       Naked short option:  ~13% SPAN + 3% Exposure + 5% peak-margin buffer
                            of the underlying notional, minus premium received
       Naked short future: ~14% of notional
       Long option:         premium debit only
       Defined-risk spread: max(|max_loss|+debit, 5% of naked stack)
       Long equity (CNC):   full price × qty
"""
from __future__ import annotations

import logging
import math
from typing import Any

import httpx

from app.config import settings
from app.fyers import client as fy
from app.fyers.symbols import resolve, SymbolInfo

log = logging.getLogger("reyu.margin")

# Naked-short % of underlying notional. Calibrated against Zerodha/Groww
# Jan 2026 quotes for ATM index options and stock options.
SPAN_INDEX = 0.13            # index options (NIFTY/BANKNIFTY/FINNIFTY/SENSEX…)
SPAN_STOCK = 0.20            # stock options
EXPOSURE_PCT = 0.03
PEAK_BUFFER = 0.05           # SEBI peak-margin headroom
FUTURE_MARGIN_PCT = 0.14
MIN_SHORT_MARGIN_PCT = 0.08  # absolute floor — never less than this

FYERS_MARGIN_URL = "https://api-t1.fyers.in/api/v3/multiorder/margin"


async def _fyers_span(legs: list[dict]) -> dict[str, Any] | None:
    """Direct HTTP call — SDK does not expose this."""
    token = await fy.get_access_token()
    if not token:
        return None
    headers = {
        "Authorization": f"{settings.fyers_app_id}:{token}",
        "Content-Type": "application/json",
    }
    payload = {
        "data": [{
            "symbol": l["symbol"],
            "qty": int(l["qty"]),
            "side": 1 if l["action"] == "BUY" else -1,
            "type": 2,                       # MARKET for margin estimate
            "productType": l.get("product", "INTRADAY"),
            "limitPrice": float(l.get("price", 0) or 0),
            "stopLoss": 0.0,
            "stopPrice": 0.0,
            "takeProfit": 0.0,
        } for l in legs]
    }
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.post(FYERS_MARGIN_URL, headers=headers, json=payload)
            data = r.json() if r.content else {}
    except Exception as e:
        log.warning("fyers margin call failed: %s", e)
        return None
    if data.get("s") != "ok":
        log.info("fyers margin non-ok response: %s", data.get("message") or data.get("code"))
        return None
    return data.get("data") or data


def _is_index(underlying: str | None) -> bool:
    if not underlying:
        return False
    return underlying.upper() in {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
                                  "SENSEX", "BANKEX", "NIFTYNXT50"}


def _has_naked_short(legs: list[dict]) -> bool:
    short_ce = any(l["action"] == "SELL" and l.get("option_type") == "CE" for l in legs)
    short_pe = any(l["action"] == "SELL" and l.get("option_type") == "PE" for l in legs)
    long_ce = any(l["action"] == "BUY" and l.get("option_type") == "CE" for l in legs)
    long_pe = any(l["action"] == "BUY" and l.get("option_type") == "PE" for l in legs)
    short_fut = any(l["action"] == "SELL" and l.get("instrument") == "FUTURE" for l in legs)
    return (short_ce and not long_ce) or (short_pe and not long_pe) or short_fut


async def _per_leg_unhedged(legs: list[dict], spot_lookup: dict[str, float]) -> list[dict]:
    out = []
    for l in legs:
        info: SymbolInfo = await resolve(l["symbol"])
        spot = spot_lookup.get(info.underlying or l["symbol"], 0)
        qty = int(l["qty"])
        premium = float(l.get("price", 0) or 0) * qty
        notional = (spot or l.get("strike") or 0) * qty

        margin = 0.0
        kind = info.instrument
        if kind == "OPTION":
            if l["action"] == "BUY":
                margin = premium
            else:
                span_pct = SPAN_INDEX if _is_index(info.underlying) else SPAN_STOCK
                total_pct = span_pct + EXPOSURE_PCT + PEAK_BUFFER
                # The premium you receive offsets the margin requirement
                margin = max(
                    notional * total_pct - premium,
                    notional * MIN_SHORT_MARGIN_PCT,
                )
        elif kind == "FUTURE":
            margin = notional * FUTURE_MARGIN_PCT
        elif kind == "EQUITY":
            margin = premium if l.get("product", "CNC") == "CNC" else premium * 0.20

        out.append({
            "symbol": l["symbol"],
            "instrument": kind,
            "lots": qty // info.lot_size if info.lot_size > 1 else qty,
            "premium": round(premium, 2),
            "notional": round(notional, 2),
            "margin_unhedged": round(max(margin, 0), 2),
        })
    return out


def _parse_fyers_total(data: dict) -> float:
    """Fyers returns slightly different keys across endpoints/versions."""
    for k in ("total", "margin_total", "total_requirement", "margin_new_order",
              "totalMargin", "marginTotal"):
        v = data.get(k)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    return 0.0


async def estimate(
    legs: list[dict],
    payoff: dict | None = None,
    spot: float | None = None,
) -> dict[str, Any]:
    if not legs:
        return {"total": 0, "per_leg": [], "source": "empty"}

    # ----- 1. Fyers live margin -----
    live = await _fyers_span(legs)
    if live:
        total = _parse_fyers_total(live)
        if total > 0:
            return {
                "total": round(total, 2),
                "span": live.get("span_margin") or live.get("var_margin"),
                "exposure": live.get("exposure_margin"),
                "premium": live.get("premium"),
                "per_leg": live.get("margin_avail") or live.get("legs") or [],
                "source": "fyers",
                "raw_keys": list(live.keys()),  # for debugging
            }

    # ----- 2. Estimate fallback -----
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
        (1 if l["action"] == "BUY" else -1) * float(l.get("price", 0) or 0) * int(l["qty"])
        for l in legs
    )

    if long_only:
        total = max(net_debit, 0)
        category = "long-only (premium only)"
    elif not naked_short and payoff and math.isfinite(payoff.get("max_loss", 0)):
        # Defined-risk spread (e.g. vertical, condor) — broker margin is
        # exactly |max_loss| + any debit paid. No floor: that's the whole
        # point of a hedged structure. Floor only applies if max_loss is 0
        # (a credit spread with no risk → still need debit/credit).
        max_loss = abs(payoff["max_loss"])
        total = max(max_loss + max(net_debit, 0), abs(net_debit))
        total = min(total, unhedged_total)
        category = "defined-risk spread"
    else:
        # Naked / undefined → full unhedged stack
        total = unhedged_total
        category = "naked short / undefined risk"

    return {
        "total": round(total, 2),
        "category": category,
        "per_leg": per_leg,
        "premium_debit": round(net_debit, 2),
        "naked_baseline": round(unhedged_total, 2),
        "source": "estimate",
    }
