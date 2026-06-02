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

from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, OptionSnapshot, Tick1m, Instrument
from app.fyers import client as fy

router = APIRouter()
BUCKETS = {"1m": 1, "5m": 5, "15m": 15}

# NSE / BSE cash + F&O segment opens at 09:15 IST. We store timestamps in
# naïve UTC, so the equivalent is 03:45 UTC of the same calendar date.
IST = timezone(timedelta(hours=5, minutes=30))


def market_open_utc(now: datetime | None = None) -> datetime:
    """Returns today's 09:15 IST converted to naïve UTC for DB comparison.

    If called before today's open (rare for an interactive query), returns
    the previous trading session's open instead so the user still sees data.
    """
    now = (now or datetime.utcnow()).replace(tzinfo=timezone.utc)
    ist_now = now.astimezone(IST)
    open_ist = ist_now.replace(hour=9, minute=15, second=0, microsecond=0)
    if ist_now < open_ist:
        open_ist -= timedelta(days=1)
    return open_ist.astimezone(timezone.utc).replace(tzinfo=None)


def _bucket(ts: datetime, minutes: int) -> datetime:
    discard = (ts.minute % minutes)
    return ts.replace(second=0, microsecond=0) - timedelta(minutes=discard)


@router.get("/snapshots")
async def snapshots(
    symbol: str,
    interval: Literal["1m", "5m", "15m"] = "1m",
    minutes: int = Query(240, ge=1, le=2880),
    today_only: bool = True,
    s: AsyncSession = Depends(get_session),
):
    """Aggregate chain snapshots (PCR / OI totals / max-pain) by bucket.

    `today_only=True` (default) clamps the window to today's 09:15 IST so
    the user never sees yesterday's tail bleeding into intraday charts.
    """
    lower_bound = datetime.utcnow() - timedelta(minutes=minutes)
    if today_only:
        lower_bound = max(lower_bound, market_open_utc())
    q = (
        select(OptionSnapshot)
        .where(OptionSnapshot.symbol == symbol, OptionSnapshot.ts >= lower_bound)
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


@router.get("/option-series")
async def option_series(
    symbol: str,
    interval: Literal["1m", "5m", "15m"] = "5m",
    today_only: bool = True,
):
    """Per-option-instrument intraday series (LTP + OI candles).

    Pulls 1-min candles from Fyers `history` for the option symbol itself,
    then re-buckets to the requested interval. F&O candles include OI in
    the 7th tuple slot.
    """
    now = datetime.utcnow()
    open_utc = market_open_utc(now)
    range_from = open_utc.strftime("%Y-%m-%d") if today_only else (now - timedelta(days=1)).strftime("%Y-%m-%d")
    range_to = now.strftime("%Y-%m-%d")
    try:
        hist = await fy.history(symbol, resolution="1", range_from=range_from, range_to=range_to)
    except Exception as e:
        return {"symbol": symbol, "error": str(e), "candles": []}

    candles = hist.get("candles", []) if isinstance(hist, dict) else []
    bucket_min = BUCKETS[interval]

    # Filter to today's session, then bucket
    grouped: dict[datetime, list[list]] = defaultdict(list)
    for c in candles:
        ts = datetime.utcfromtimestamp(c[0])
        if today_only and ts < open_utc:
            continue
        grouped[_bucket(ts, bucket_min)].append(c)

    rows = []
    prev_oi = None
    for ts in sorted(grouped):
        bs = grouped[ts]
        opens = bs[0][1]; closes = bs[-1][4]
        highs = max(c[2] for c in bs); lows = min(c[3] for c in bs)
        vol = sum(int(c[5] or 0) for c in bs)
        oi = int(bs[-1][6] or 0) if len(bs[-1]) > 6 else 0
        oi_change = (oi - prev_oi) if prev_oi is not None else 0
        prev_oi = oi
        rows.append({
            "ts": ts.isoformat(),
            "open": opens, "high": highs, "low": lows, "close": closes,
            "volume": vol, "oi": oi, "oi_change": oi_change,
        })

    return {"symbol": symbol, "interval": interval, "rows": rows,
            "session_start": open_utc.isoformat()}


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
