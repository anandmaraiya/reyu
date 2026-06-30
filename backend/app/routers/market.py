"""Public market data endpoints — no auth required.

GET /api/market/ticks   → latest spot prices for index symbols
                          Served from Redis cache; falls back to demo values.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/api/market", tags=["market"])

# Canonical demo/seed values — also used when Fyers is not connected.
_DEMO: dict[str, dict] = {
    "NSE:NIFTY50-INDEX":   {"label": "NIFTY",     "ltp": 24812.0, "close": 24680.0},
    "NSE:NIFTYBANK-INDEX": {"label": "BANKNIFTY",  "ltp": 53241.0, "close": 52980.0},
    "NSE:FINNIFTY-INDEX":  {"label": "FINNIFTY",   "ltp": 23540.0, "close": 23410.0},
    "NSE:INDIA VIX-INDEX": {"label": "VIX",        "ltp": 14.32,   "close": 13.95},
}

_SYMBOLS = list(_DEMO.keys())

REDIS_KEY = "market:spot_ticks"


async def _get_redis():
    try:
        from app.store import store as st
        return st.r
    except Exception:
        return None


async def _fetch_and_cache() -> list[dict]:
    """Try to fetch live quotes from Fyers and persist to Redis."""
    try:
        from app.brokers.fyers import FyersBroker
        fy = FyersBroker(user_id="system")
        quotes = await fy.get_quotes(_SYMBOLS)
        if quotes and not await fy.is_demo():
            ticks = [
                {
                    "symbol": q.symbol,
                    "label": _DEMO.get(q.symbol, {}).get("label", q.symbol.split(":")[1]),
                    "ltp": round(q.ltp, 2),
                    "close": round(q.close, 2),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                for q in quotes
            ]
            r = await _get_redis()
            if r:
                await r.set(REDIS_KEY, json.dumps(ticks), ex=120)  # 2 min TTL
            return ticks
    except Exception:
        pass
    return []


def _demo_ticks() -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {"symbol": s, "label": v["label"], "ltp": v["ltp"], "close": v["close"],
         "updated_at": now, "demo": True}
        for s, v in _DEMO.items()
    ]


async def _last_db_ticks() -> list[dict]:
    """Fallback: last row per symbol from tick_1m. Real data, just stale —
    much better than demo values when Fyers is down for a few hours."""
    try:
        from sqlalchemy import select, func
        from app.db import SessionLocal, Tick1m
        ticks: list[dict] = []
        async with SessionLocal() as s:
            for sym in _SYMBOLS:
                row = (await s.execute(
                    select(Tick1m).where(Tick1m.symbol == sym)
                    .order_by(Tick1m.ts.desc()).limit(1)
                )).scalar_one_or_none()
                if not row or row.close is None:
                    continue
                ticks.append({
                    "symbol": sym,
                    "label": _DEMO.get(sym, {}).get("label", sym.split(":")[1]),
                    "ltp": round(float(row.close), 2),
                    "close": round(float(row.open), 2),
                    "updated_at": row.ts.replace(tzinfo=timezone.utc).isoformat() if row.ts.tzinfo is None else row.ts.isoformat(),
                    "stale": True,            # signal to UI: not live
                })
        return ticks
    except Exception:
        return []


@router.get("/ticks")
async def get_ticks(symbols: Optional[str] = None):
    """
    Public endpoint — returns latest spot prices.
    Priority: Redis cache → live Fyers fetch → demo values.
    No authentication required.
    """
    r = await _get_redis()

    # 1. Redis cache
    if r:
        cached = await r.get(REDIS_KEY)
        if cached:
            ticks = json.loads(cached)
            if symbols:
                sym_set = {s.strip() for s in symbols.split(",")}
                ticks = [t for t in ticks if t["symbol"] in sym_set]
            return {"ticks": ticks, "demo": False}

    # 2. Live fetch (also caches result)
    live = await _fetch_and_cache()
    if live:
        if symbols:
            sym_set = {s.strip() for s in symbols.split(",")}
            live = [t for t in live if t["symbol"] in sym_set]
        return {"ticks": live, "demo": False}

    # 3. Last captured tick_1m row per symbol (real, but possibly stale by
    # minutes/hours/days). Much better than demo when Fyers is offline.
    db = await _last_db_ticks()
    if db:
        if symbols:
            sym_set = {s.strip() for s in symbols.split(",")}
            db = [t for t in db if t["symbol"] in sym_set]
        if db:
            return {"ticks": db, "demo": False, "stale": True}

    # 4. Demo fallback — only when DB has nothing for the requested symbols.
    ticks = _demo_ticks()
    if symbols:
        sym_set = {s.strip() for s in symbols.split(",")}
        ticks = [t for t in ticks if t["symbol"] in sym_set]
    return {"ticks": ticks, "demo": True}


@router.post("/ticks/refresh")
async def refresh_ticks():
    """Force a fresh Fyers fetch and update the Redis cache. Called by the morning batch."""
    ticks = await _fetch_and_cache()
    return {"ok": True, "count": len(ticks), "demo": len(ticks) == 0}
