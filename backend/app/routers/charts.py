"""Server-side chart image endpoints.

POST  /api/chart/payoff     { underlying, legs[, range_pct, points] }  -> PNG
GET   /api/chart/oi         ?symbol=&strikecount=                     -> PNG
GET   /api/chart/pcr        ?symbol=&interval=                        -> PNG
GET   /api/chart/iv-smile   ?symbol=&strikecount=                     -> PNG

All return image/png. Public read-only -- the agent and any future
Telegram/Discord bots can hot-link these in their replies.

Rendered charts are cached in Redis (keyed by params hash) with a
configurable TTL so repeated views / agent calls are instant.
"""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from datetime import datetime, timedelta

from app.fyers import client as fy
from app.analytics.chain import normalize_chain
from app.analytics.payoff import compute as compute_payoff
from app.charts.render import (
    render_payoff, render_oi_distribution, render_pcr_timeseries,
    render_iv_smile,
)
from app.routers.timeseries import market_open_utc, BUCKETS, _bucket
from app.db import get_session, OptionSnapshot
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from collections import defaultdict

router = APIRouter()

CHART_CACHE_TTL = 60 * 5   # 5 minutes


def _cache_key(prefix: str, params: dict) -> str:
    blob = json.dumps(params, sort_keys=True, default=str).encode("utf-8")
    h = hashlib.md5(blob).hexdigest()[:12]
    return f"chart:{prefix}:{h}"

async def _cached_or_render(prefix: str, params: dict, render_fn) -> bytes:
    """Return cached PNG or render, cache, and return."""
    from app.store import store
    import base64
    key = _cache_key(prefix, params)
    cached = await store.r.get(key)
    if cached:
        return base64.b64decode(cached) if isinstance(cached, str) else cached
    png = render_fn()
    # Store as base64 string since Redis client has decode_responses=True
    await store.r.set(key, base64.b64encode(png).decode(), ex=CHART_CACHE_TTL)
    return png


class PayoffChartLeg(BaseModel):
    symbol: str
    action: str
    qty: int
    price: float = 0
    strike: float | None = None
    option_type: str | None = None


class PayoffChartRequest(BaseModel):
    underlying: str = "NSE:NIFTY50-INDEX"
    legs: list[PayoffChartLeg]
    range_pct: float = 0.12
    points: int = 121


@router.post("/payoff", responses={200: {"content": {"image/png": {}}}})
async def chart_payoff(req: PayoffChartRequest):
    raw = await fy.option_chain(req.underlying, 25)
    chain = normalize_chain(raw)

    chain_lookup: dict[str, dict] = {}
    for row in chain.get("strikes", []):
        for side in ("ce", "pe"):
            leg = row.get(side)
            if leg and leg.get("symbol"):
                chain_lookup[leg["symbol"]] = {**leg, "strike": row["strike"], "option_type": side.upper()}
    legs: list[dict] = []
    for l in req.legs:
        m = chain_lookup.get(l.symbol, {})
        legs.append({
            "symbol": l.symbol, "instrument": "OPTION",
            "strike": l.strike if l.strike is not None else m.get("strike"),
            "option_type": l.option_type or m.get("option_type"),
            "action": l.action, "qty": l.qty,
            "price": l.price or (m.get("ltp") or 0),
        })

    payoff = compute_payoff(legs, spot=chain["ltp"], range_pct=req.range_pct, points=req.points)
    if "points" not in payoff:
        raise HTTPException(400, payoff.get("error", "payoff computation failed"))

    title = f"{req.underlying} -- {len(legs)}-leg payoff @ expiry"
    params = {"underlying": req.underlying, "legs": [l.dict() for l in req.legs],
              "range_pct": req.range_pct, "points": req.points}
    png = await _cached_or_render("payoff", params, lambda: render_payoff(payoff, title=title))
    return Response(png, media_type="image/png")


@router.get("/oi", responses={200: {"content": {"image/png": {}}}})
async def chart_oi(symbol: str = Query(..., description="e.g. NSE:NIFTY50-INDEX"),
                   strikecount: int = 25):
    raw = await fy.option_chain(symbol, strikecount)
    chain = normalize_chain(raw)
    params = {"symbol": symbol, "strikecount": strikecount}
    png = await _cached_or_render("oi", params, lambda: render_oi_distribution(
        chain["strikes"], spot=chain["ltp"],
        max_pain=chain["summary"].get("max_pain"),
        atm=chain["summary"].get("atm_strike"),
        title=f"{symbol} -- OI distribution",
    ))
    return Response(png, media_type="image/png")


@router.get("/pcr", responses={200: {"content": {"image/png": {}}}})
async def chart_pcr(symbol: str = Query(...),
                    interval: str = "5m",
                    s: AsyncSession = Depends(get_session)):
    lower_bound = max(datetime.utcnow() - timedelta(days=1), market_open_utc())
    q = (
        select(OptionSnapshot)
        .where(OptionSnapshot.symbol == symbol, OptionSnapshot.ts >= lower_bound)
        .order_by(OptionSnapshot.ts)
    )
    rows = (await s.execute(q)).scalars().all()
    bucket_min = BUCKETS.get(interval, 5)
    grouped = defaultdict(list)
    for r in rows:
        grouped[_bucket(r.ts, bucket_min)].append(r)

    out = []
    for ts in sorted(grouped):
        bs = grouped[ts]
        first, last = bs[0], bs[-1]
        out.append({
            "ts": ts.isoformat(),
            "ltp": last.ltp,
            "pcr_oi": sum(b.pcr_oi for b in bs) / len(bs),
            "ce_oi_delta": (last.total_ce_oi or 0) - (first.total_ce_oi or 0),
            "pe_oi_delta": (last.total_pe_oi or 0) - (first.total_pe_oi or 0),
        })

    params = {"symbol": symbol, "interval": interval}
    png = await _cached_or_render("pcr", params, lambda: render_pcr_timeseries(
        out, title=f"{symbol} -- PCR & delta-OI"
    ))
    return Response(png, media_type="image/png")


@router.get("/iv-smile", responses={200: {"content": {"image/png": {}}}})
async def chart_iv_smile(symbol: str = Query(..., description="e.g. NSE:NIFTY50-INDEX"),
                         strikecount: int = 25):
    """Plot CE and PE implied volatility across strikes (the volatility smile)."""
    raw = await fy.option_chain(symbol, strikecount)
    chain = normalize_chain(raw)
    params = {"symbol": symbol, "strikecount": strikecount}
    png = await _cached_or_render("iv-smile", params, lambda: render_iv_smile(
        chain["strikes"], spot=chain["ltp"],
        atm=chain["summary"].get("atm_strike"),
        title=f"{symbol} -- IV smile",
    ))
    return Response(png, media_type="image/png")
