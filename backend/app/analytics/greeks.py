"""Black-Scholes Greeks + IV solver.

Used when the Fyers option-chain payload does not include Greeks, or when a
caller wants a consistent model-based view across symbols.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from scipy.stats import norm
from scipy.optimize import brentq


@dataclass
class Greeks:
    price: float
    delta: float
    gamma: float
    theta: float  # per day
    vega: float   # per 1% IV change
    rho: float
    iv: float


def _d1_d2(S, K, T, r, sigma):
    sigma = max(sigma, 1e-6)
    T = max(T, 1e-6)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def bs_price(S: float, K: float, T: float, r: float, sigma: float, kind: str) -> float:
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    if kind.upper() == "CE":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def implied_vol(price: float, S: float, K: float, T: float, r: float, kind: str) -> float:
    if price <= 0 or T <= 0:
        return 0.0
    try:
        return brentq(lambda s: bs_price(S, K, T, r, s, kind) - price, 1e-4, 5.0, maxiter=100)
    except Exception:
        return 0.0


def greeks(S: float, K: float, T: float, r: float, sigma: float, kind: str) -> Greeks:
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    pdf = norm.pdf(d1)
    sign = 1 if kind.upper() == "CE" else -1
    price = bs_price(S, K, T, r, sigma, kind)
    delta = sign * norm.cdf(sign * d1)
    gamma = pdf / (S * sigma * math.sqrt(T))
    theta = (
        -(S * pdf * sigma) / (2 * math.sqrt(T))
        - sign * r * K * math.exp(-r * T) * norm.cdf(sign * d2)
    ) / 365.0
    vega = S * pdf * math.sqrt(T) / 100.0
    rho = sign * K * T * math.exp(-r * T) * norm.cdf(sign * d2) / 100.0
    return Greeks(price, delta, gamma, theta, vega, rho, sigma)
