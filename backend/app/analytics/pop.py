"""Probability-of-profit using log-normal model around the IV-implied 1σ move.

For a payoff curve {S_i, pnl_i} and an underlying spot/IV/DTE we estimate:
  - sigma_T = atm_iv * sqrt(DTE/365)
  - log-normal pdf around spot
  - POP = ∫ pdf(S) for S where pnl(S) > 0
"""
from __future__ import annotations
import math


def lognormal_pdf(S: float, spot: float, sigma_T: float) -> float:
    if S <= 0 or spot <= 0 or sigma_T <= 0:
        return 0
    x = math.log(S / spot)
    return math.exp(-(x ** 2) / (2 * sigma_T ** 2)) / (S * sigma_T * math.sqrt(2 * math.pi))


def probability_of_profit(payoff_points: list[dict], spot: float, atm_iv: float, dte_days: float) -> dict:
    if not payoff_points or spot <= 0:
        return {"pop": None, "sigma_pct": None}
    sigma_T = (atm_iv or 0.20) * math.sqrt(max(dte_days, 1) / 365)
    total_w = 0.0
    profit_w = 0.0
    for i in range(1, len(payoff_points)):
        a, b = payoff_points[i - 1], payoff_points[i]
        mid_S = (a["S"] + b["S"]) / 2
        mid_pnl = (a["pnl"] + b["pnl"]) / 2
        w = lognormal_pdf(mid_S, spot, sigma_T) * (b["S"] - a["S"])
        total_w += w
        if mid_pnl > 0:
            profit_w += w
    pop = (profit_w / total_w) if total_w > 0 else None
    return {"pop": round(pop, 4) if pop is not None else None,
            "sigma_pct": round(sigma_T * 100, 2),
            "expected_1sd_range": [round(spot * math.exp(-sigma_T), 2),
                                    round(spot * math.exp(sigma_T), 2)]}
