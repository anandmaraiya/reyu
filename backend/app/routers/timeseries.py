"""Time-series queries on top of the option_snapshot + tick_1m tables.

Endpoints:
  GET /api/ts/snapshots?symbol=...&interval=1m|5m|15m&minutes=...
  GET /api/ts/ticks?symbol=...&minutes=...
  GET /api/ts/oi-change?symbol=...&interval=5m|15m
  GET /api/ts/instruments    list of every instrument we know about

Aggregation is done in-process to avoid relying on Timescale-specific funcs
(`time_bucket` works only on the Timescale image). For 5m / 15m views we
bucket the per-minute snapshots and compute window-deltas for OI.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, OptionSnapshot, Tick1m, Instrument

router = APIRouter()
BUCKETS = {"1m": 1, "5m": 5, "15m": 15}


def _bucket(ts: datetime, minutes: int) -> datetime:
    discard = (ts.minute % minutes)
    return ts.replace(second=0, microsecond=0) - timedelta(minutes=discard)


@router.get("/snapshots")
async def snapshots(
    symbol: str,
    interval: Literal["1m", "5m", "15m"] = "1m",
    minutes: int = Query(240, ge=1, le=2880),
    s: AsyncSession = Depends(get_session),
):
    since = datetime.utcnow() - timedelta(minutes=minutes)
    q = (
        select(OptionSnapshot)
        .where(OptionSnapshot.symbol == symbol, OptionSnapshot.ts >= since)
        .order_by(OptionSnapshot.ts)
    )
    rows = (await s.execute(q)).scalars().all()
    bucket_min = BUCKETS[interval]

    grouped: dict[datetime, list[OptionSnapshot]] = defaultdict(list)
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
            "pcr_volume": sum(b.pcr_volume for b in bs) / len(bs),
            "max_pain": last.max_pain,
            "atm_iv": last.atm_iv,
            "total_ce_oi": last.total_ce_oi,
            "total_pe_oi": last.total_pe_oi,
            # Window deltas: how much OI changed vs the start of this bucket
            "ce_oi_delta": (last.total_ce_oi or 0) - (first.total_ce_oi or 0),
            "pe_oi_delta": (last.total_pe_oi or 0) - (first.total_pe_oi or 0),
            "bias_score": last.bias_score,
        })
    return {"symbol": symbol, "interval": interval, "rows": out}


@router.get("/ticks")
async def ticks(
    symbol: str,
    minutes: int = Query(240, ge=1, le=2880),
    s: AsyncSession = Depends(get_session),
):
    since = datetime.utcnow() - timedelta(minutes=minutes)
    q = (
        select(Tick1m)
        .where(Tick1m.symbol == symbol, Tick1m.ts >= since)
        .order_by(Tick1m.ts)
    )
    rows = (await s.execute(q)).scalars().all()
    return {
        "symbol": symbol,
        "candles": [
            {"ts": r.ts.isoformat(), "o": r.open, "h": r.high, "l": r.low,
             "c": r.close, "v": r.volume, "oi": r.oi}
            for r in rows
        ],
    }


@router.get("/oi-change")
async def oi_change(
    symbol: str,
    interval: Literal["5m", "15m"] = "5m",
    minutes: int = Query(240, ge=15, le=2880),
    s: AsyncSession = Depends(get_session),
):
    """Rolling per-window OI delta — what writers/longs did over each bucket."""
    data = await snapshots.__wrapped__(symbol=symbol, interval=interval,
                                       minutes=minutes, s=s) if False else None  # noqa
    # Reuse snapshots logic directly:
    return await snapshots(symbol=symbol, interval=interval, minutes=minutes, s=s)


@router.get("/instruments")
async def instruments(
    tracked_only: bool = False,
    s: AsyncSession = Depends(get_session),
):
    q = select(Instrument)
    if tracked_only:
        q = q.where(Instrument.tracked == 1)
    rows = (await s.execute(q.order_by(Instrument.symbol))).scalars().all()
    return [
        {"symbol": r.symbol, "name": r.name, "exch": r.exch, "segment": r.segment,
         "tracked": bool(r.tracked), "expiry": r.expiry, "strike": r.strike,
         "option_type": r.option_type, "underlying": r.underlying}
        for r in rows
    ]


@router.post("/track")
async def track(symbol: str, tracked: bool = True, s: AsyncSession = Depends(get_session)):
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    stmt = pg_insert(Instrument).values(symbol=symbol, tracked=int(tracked)).on_conflict_do_update(
        index_elements=[Instrument.symbol], set_={"tracked": int(tracked)}
    )
    await s.execute(stmt)
    await s.commit()
    return {"symbol": symbol, "tracked": tracked}
