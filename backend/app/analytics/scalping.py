"""Lightweight scalping signal generator.

Combines a fast OI delta read with intraday momentum from recent candles to
flag quick long/short setups. Intentionally simple — extend with order-flow
or VWAP filters as needed.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from app.fyers import client as fy
from app.analytics.chain import normalize_chain, trade_bias


def _momentum(candles: list[list]) -> float:
    """% change of last close vs n-bar SMA."""
    if len(candles) < 10:
        return 0.0
    closes = [c[4] for c in candles[-20:]]
    sma = sum(closes) / len(closes)
    return (closes[-1] - sma) / sma * 100


async def scalp_signal(symbol: str) -> dict[str, Any]:
    today = datetime.utcnow().date()
    raw_chain = await fy.option_chain(symbol, 10)
    chain = normalize_chain(raw_chain)
    bias = trade_bias(chain["summary"])

    try:
        hist = await fy.history(
            symbol,
            resolution="5",
            range_from=str(today - timedelta(days=2)),
            range_to=str(today),
        )
        candles = hist.get("candles", [])
    except Exception:
        candles = []

    mom = _momentum(candles)
    direction = None
    if bias["score"] >= 1 and mom > 0.2:
        direction = "LONG"
    elif bias["score"] <= -1 and mom < -0.2:
        direction = "SHORT"

    atm = chain["summary"].get("atm_strike")
    target_leg = None
    if direction and atm:
        side = "ce" if direction == "LONG" else "pe"
        row = next((s for s in chain["strikes"] if s["strike"] == atm), None)
        if row and row.get(side):
            target_leg = row[side]

    return {
        "symbol": symbol,
        "ltp": chain["ltp"],
        "bias": bias,
        "momentum_pct": mom,
        "direction": direction,
        "suggested_leg": target_leg,
        "stop_pct": 0.4 if direction else None,
        "target_pct": 0.8 if direction else None,
    }
