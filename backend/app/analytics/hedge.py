"""Hedge construction + risk-adjusted portfolio sizing.

Given a primary leg (option the user wants to buy/sell), suggest hedge legs
that flatten the portfolio Greeks toward a user-configured target.
"""
from __future__ import annotations

from typing import Any, Literal

Action = Literal["BUY", "SELL"]


def _leg_greeks(strike: dict, side: str) -> dict:
    leg = strike.get(side, {})
    return {
        "symbol": leg.get("symbol"),
        "strike": strike["strike"],
        "side": side.upper(),
        "ltp": leg.get("ltp", 0),
        "delta": leg.get("delta") or 0,
        "gamma": leg.get("gamma") or 0,
        "theta": leg.get("theta") or 0,
        "vega": leg.get("vega") or 0,
        "oi": leg.get("oi", 0),
    }


def suggest_hedge(
    chain: dict[str, Any],
    primary_symbol: str,
    primary_action: Action,
    qty: int = 1,
    target_delta: float = 0.0,
    max_cost: float | None = None,
) -> dict[str, Any]:
    """Recommend hedge legs that bring net delta close to `target_delta`.

    Strategy:
      - If primary is long CE (positive delta) -> short OTM CE or long OTM PE
      - If primary is long PE (negative delta) -> long OTM CE or short OTM PE
      - Mirror logic for short primary
    """
    legs: list[dict] = []
    for strike in chain["strikes"]:
        for side in ("ce", "pe"):
            if strike.get(side, {}).get("symbol") == primary_symbol:
                legs.append({**_leg_greeks(strike, side), "action": primary_action, "qty": qty})
                break

    if not legs:
        return {"error": "primary leg not found in chain"}

    primary = legs[0]
    sign = 1 if primary["action"] == "BUY" else -1
    net_delta = sign * primary["delta"] * qty
    net_vega = sign * primary["vega"] * qty

    # Candidates: opposite-side strikes within +/- 10% of spot
    spot = chain.get("ltp") or primary["strike"]
    candidates = []
    for strike in chain["strikes"]:
        if abs(strike["strike"] - spot) / spot > 0.10:
            continue
        for side in ("ce", "pe"):
            leg = strike.get(side)
            if not leg or leg.get("symbol") == primary_symbol:
                continue
            candidates.append(_leg_greeks(strike, side))

    # Pick hedge that minimises |net_delta + hedge_delta * hedge_sign * q|
    best = None
    for c in candidates:
        if not c["delta"]:
            continue
        for action in ("BUY", "SELL"):
            hsign = 1 if action == "BUY" else -1
            # solve for q (1..5) that brings delta closest to target
            for q in range(1, 6):
                resid = net_delta + hsign * c["delta"] * q - target_delta
                cost = hsign * c["ltp"] * q  # debit positive
                if max_cost is not None and cost > max_cost:
                    continue
                score = abs(resid) + 0.001 * abs(net_vega + hsign * c["vega"] * q)
                if best is None or score < best["score"]:
                    best = {"leg": c, "action": action, "qty": q, "resid_delta": resid, "score": score, "cost": cost}

    hedge_legs = []
    if best:
        hedge_legs.append({**best["leg"], "action": best["action"], "qty": best["qty"]})

    all_legs = legs + hedge_legs
    portfolio = {
        "delta": sum((1 if l["action"] == "BUY" else -1) * l["delta"] * l["qty"] for l in all_legs),
        "gamma": sum((1 if l["action"] == "BUY" else -1) * l["gamma"] * l["qty"] for l in all_legs),
        "theta": sum((1 if l["action"] == "BUY" else -1) * l["theta"] * l["qty"] for l in all_legs),
        "vega": sum((1 if l["action"] == "BUY" else -1) * l["vega"] * l["qty"] for l in all_legs),
        "net_debit": sum((1 if l["action"] == "BUY" else -1) * l["ltp"] * l["qty"] for l in all_legs),
    }
    return {"legs": all_legs, "portfolio_greeks": portfolio}
