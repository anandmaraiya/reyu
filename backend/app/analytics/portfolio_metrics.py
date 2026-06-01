"""Lightweight risk metrics for portfolios.

We don't yet store per-portfolio P&L time series, so for now we use the
underlying's tick_1m candles (mark-to-market proxy) and net leg directions.
Returns Sharpe, MaxDD, win-rate (positive bar fraction), volatility.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from sqlalchemy import select
from app.db import SessionLocal, Tick1m


async def metrics_for_legs(legs: list[dict], minutes: int = 1440) -> dict:
    """Returns risk metrics using each leg's underlying price series."""
    if not legs:
        return {}
    since = datetime.utcnow() - timedelta(minutes=minutes)

    # Aggregate intra-day equity curve: Σ_i sign_i * qty_i * (close_t - entry_i)
    points: dict[datetime, float] = {}
    async with SessionLocal() as s:
        for l in legs:
            rows = (await s.execute(
                select(Tick1m).where(Tick1m.symbol == l["symbol"], Tick1m.ts >= since).order_by(Tick1m.ts)
            )).scalars().all()
            entry = l.get("entry_price") or l.get("price") or 0
            sign = 1 if l["action"] == "BUY" else -1
            for r in rows:
                pnl = sign * (r.close - entry) * l["qty"]
                points[r.ts] = points.get(r.ts, 0) + pnl

    if len(points) < 5:
        return {"sharpe": None, "max_drawdown": None, "win_rate": None, "vol": None}

    series = [v for _, v in sorted(points.items())]
    rets = [series[i] - series[i - 1] for i in range(1, len(series))]
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / max(len(rets) - 1, 1)
    std = math.sqrt(var)
    # Annualised approximation: minute bars * sqrt(525960)
    sharpe = (mean / std) * math.sqrt(525960) if std > 0 else None
    win_rate = sum(1 for x in rets if x > 0) / len(rets)
    # Max drawdown from running peak
    peak = series[0]; max_dd = 0
    for v in series:
        peak = max(peak, v)
        max_dd = min(max_dd, v - peak)

    return {
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "max_drawdown": round(max_dd, 2),
        "win_rate": round(win_rate, 3),
        "vol_per_min": round(std, 2),
        "samples": len(rets),
    }
