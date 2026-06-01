"""Strategy payoff engine.

For an arbitrary basket of option/future/equity legs, compute:
  - P&L grid across underlying prices in [spot * (1-range), spot * (1+range)]
  - Max profit, max loss
  - Breakeven points (where the curve crosses zero)
  - P&L at current spot
  - Aggregate Greeks (only for legs with Greeks supplied)

Leg shape:
  { symbol, instrument, strike?, option_type?, action: BUY|SELL,
    qty, price (entry premium), delta?, gamma?, theta?, vega? }
"""
from __future__ import annotations

import numpy as np
from typing import Any


def _leg_payoff(leg: dict, S: np.ndarray) -> np.ndarray:
    sign = 1 if leg["action"] == "BUY" else -1
    qty = leg["qty"]
    entry = leg.get("price", 0) or 0
    inst = leg.get("instrument", "OPTION")

    if inst == "OPTION":
        K = leg["strike"]
        if leg["option_type"] == "CE":
            intrinsic = np.maximum(S - K, 0)
        else:
            intrinsic = np.maximum(K - S, 0)
        return sign * (intrinsic - entry) * qty

    if inst == "FUTURE":
        return sign * (S - entry) * qty

    # EQUITY
    return sign * (S - entry) * qty


def _breakevens(S: np.ndarray, pnl: np.ndarray) -> list[float]:
    out = []
    for i in range(1, len(pnl)):
        if pnl[i - 1] == 0:
            out.append(float(S[i - 1]))
        elif (pnl[i - 1] < 0 and pnl[i] > 0) or (pnl[i - 1] > 0 and pnl[i] < 0):
            # linear interp
            x = S[i - 1] + (S[i] - S[i - 1]) * (-pnl[i - 1] / (pnl[i] - pnl[i - 1]))
            out.append(round(float(x), 2))
    return out


def compute(legs: list[dict], spot: float, range_pct: float = 0.10, points: int = 121) -> dict[str, Any]:
    if not legs or spot <= 0:
        return {"error": "need legs and spot > 0"}

    S = np.linspace(spot * (1 - range_pct), spot * (1 + range_pct), points)
    total = np.zeros_like(S)
    for l in legs:
        total += _leg_payoff(l, S)

    pnl_now = float(np.interp(spot, S, total))

    # Aggregate Greeks (sign-applied)
    greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for l in legs:
        sign = 1 if l["action"] == "BUY" else -1
        for k in greeks:
            v = l.get(k) or 0
            greeks[k] += sign * v * l["qty"]

    net_debit = sum(
        (1 if l["action"] == "BUY" else -1) * (l.get("price", 0) or 0) * l["qty"]
        for l in legs
    )

    return {
        "spot": spot,
        "points": [{"S": round(float(s), 2), "pnl": round(float(p), 2)} for s, p in zip(S, total)],
        "max_profit": round(float(np.max(total)), 2),
        "max_loss": round(float(np.min(total)), 2),
        "pnl_at_spot": round(pnl_now, 2),
        "breakevens": _breakevens(S, total),
        "greeks": {k: round(v, 4) for k, v in greeks.items()},
        "net_debit": round(net_debit, 2),
    }
