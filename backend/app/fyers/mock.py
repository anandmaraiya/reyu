"""Synthetic Fyers responses for Demo Mode.

When Fyers isn't authenticated we serve a fabricated NIFTY-style chain so the
full UI is explorable. Demo data is deterministic per symbol so screenshots
and onboarding tours stay consistent.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Any


def _seed_for(symbol: str) -> random.Random:
    return random.Random(hash(symbol) & 0xFFFFFFFF)


DEMO_SPOT = {
    "NSE:NIFTY50-INDEX": 24800,
    "NSE:NIFTYBANK-INDEX": 53200,
    "NSE:FINNIFTY-INDEX": 26500,
    "NSE:MIDCPNIFTY-INDEX": 13200,
    "BSE:SENSEX-INDEX": 81100,
    "NSE:RELIANCE-EQ": 1230,
    "NSE:HDFCBANK-EQ": 1690,
    "NSE:INFY-EQ": 1820,
    "NSE:TCS-EQ": 4150,
    "NSE:ICICIBANK-EQ": 1340,
}


def mock_quotes(symbols: list[str]) -> dict[str, Any]:
    out = []
    for s in symbols:
        r = _seed_for(s)
        spot = DEMO_SPOT.get(s, 1000 + r.uniform(-50, 200))
        out.append({"n": s, "s": "ok", "v": {"lp": round(spot, 2),
                                              "ch": round(r.uniform(-spot * 0.005, spot * 0.005), 2),
                                              "chp": round(r.uniform(-0.5, 0.5), 2)}})
    return {"s": "ok", "d": out}


def _bs_call(S, K, T, sigma):
    from math import log, sqrt, exp
    from scipy.stats import norm
    sigma = max(sigma, 0.01); T = max(T, 1e-4)
    d1 = (log(S / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    return max(S * norm.cdf(d1) - K * 0.99 * norm.cdf(d2), 0.05)


def mock_option_chain(symbol: str, strikecount: int = 25) -> dict[str, Any]:
    r = _seed_for(symbol)
    spot = DEMO_SPOT.get(symbol, 24800)
    # spacing 50 for nifty, 100 for banknifty, 1% of price for stocks
    spacing = 50 if "NIFTY50" in symbol else 100 if "BANK" in symbol else max(round(spot * 0.005, 0), 1)
    atm = round(spot / spacing) * spacing
    expiry_dt = datetime.utcnow() + timedelta(days=7 - datetime.utcnow().weekday())
    expiry_ts = int(expiry_dt.timestamp())
    T = max((expiry_ts - datetime.utcnow().timestamp()) / (365 * 24 * 3600), 1 / 365)

    rows = []
    half = strikecount // 2
    for i in range(-half, half + 1):
        K = atm + i * spacing
        # IV smile: ATM lowest, wings higher
        moneyness = abs(K - spot) / spot
        iv_ce = 0.14 + moneyness * 0.6 + r.uniform(-0.01, 0.01)
        iv_pe = 0.15 + moneyness * 0.55 + r.uniform(-0.01, 0.01)
        ce_ltp = _bs_call(spot, K, T, iv_ce)
        pe_ltp = max(_bs_call(K, spot, T, iv_pe) + (K - spot) * 0.001, 0.05)
        ce_oi = int(max(r.gauss(80000 - abs(i) * 4000, 15000), 0))
        pe_oi = int(max(r.gauss(85000 - abs(i) * 4500, 15000), 0))
        ce_oich = int(r.gauss(0, 8000)); pe_oich = int(r.gauss(0, 8000))
        ce_vol = int(max(r.gauss(40000 - abs(i) * 2000, 10000), 0))
        pe_vol = int(max(r.gauss(42000 - abs(i) * 2000, 10000), 0))

        # Build CE and PE rows in Fyers' shape
        sym_base = symbol.replace('-INDEX', '').replace('-EQ', '')
        ce_sym = f"{sym_base}{expiry_dt:%y%b}{int(K)}CE".upper()
        pe_sym = f"{sym_base}{expiry_dt:%y%b}{int(K)}PE".upper()
        rows.append({"symbol": ce_sym, "strike_price": K, "option_type": "CE",
                     "ltp": round(ce_ltp, 2), "oi": ce_oi, "oich": ce_oich,
                     "volume": ce_vol, "iv": round(iv_ce, 4)})
        rows.append({"symbol": pe_sym, "strike_price": K, "option_type": "PE",
                     "ltp": round(pe_ltp, 2), "oi": pe_oi, "oich": pe_oich,
                     "volume": pe_vol, "iv": round(iv_pe, 4)})

    return {
        "s": "ok",
        "data": {
            "symbol": symbol, "ltp": spot, "expiry": expiry_ts,
            "expiryData": [{"date": expiry_dt.strftime("%d-%b-%Y"), "expiry": expiry_ts},
                            {"date": (expiry_dt + timedelta(days=7)).strftime("%d-%b-%Y"),
                             "expiry": expiry_ts + 7 * 86400},
                            {"date": (expiry_dt + timedelta(days=28)).strftime("%d-%b-%Y"),
                             "expiry": expiry_ts + 28 * 86400}],
            "optionsChain": rows,
        },
    }


def mock_history(symbol: str, resolution: str, _from: str, _to: str) -> dict[str, Any]:
    r = _seed_for(symbol + resolution)
    spot = DEMO_SPOT.get(symbol, 24800)
    ts = int(datetime.utcnow().timestamp())
    step = 60 if resolution == "1" else 300 if resolution == "5" else 900
    candles = []
    price = spot
    for i in range(200):
        o = price
        c = price + r.uniform(-spot * 0.001, spot * 0.001)
        h = max(o, c) + r.uniform(0, spot * 0.0005)
        l = min(o, c) - r.uniform(0, spot * 0.0005)
        v = int(r.uniform(5e5, 5e6))
        candles.append([ts - (200 - i) * step, round(o, 2), round(h, 2), round(l, 2), round(c, 2), v])
        price = c
    return {"s": "ok", "candles": candles}


def mock_positions() -> dict[str, Any]:
    return {"s": "ok", "netPositions": []}
