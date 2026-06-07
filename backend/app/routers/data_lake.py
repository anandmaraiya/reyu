"""Data-lake admin endpoints — Sprint 0.2.

POST /api/data/bhavcopy/fetch?date=YYYY-MM-DD
POST /api/data/bhavcopy/backfill?start=...&end=...   (async background)
GET  /api/data/bhavcopy/status                       (coverage report)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, OptionEod, OptionContract1m
from sqlalchemy import select, func
from app.data import bhavcopy, option_history

router = APIRouter()
log = logging.getLogger("reyu.routers.data_lake")


@router.post("/bhavcopy/fetch")
async def bhavcopy_fetch_one(
    target_date: date = Query(..., alias="date"),
):
    """Pull + ingest a single date. Synchronous (~2-5s)."""
    res = await bhavcopy.fetch_one(target_date)
    return res


@router.post("/bhavcopy/backfill")
async def bhavcopy_backfill(
    start: date,
    end: date,
    background: BackgroundTasks,
):
    """Multi-day backfill. Runs in background — caller polls /status."""
    if (end - start).days > 365 * 10:
        raise HTTPException(400, "Max 10-year range per call")
    if end < start:
        raise HTTPException(400, "end must be >= start")

    async def _runner():
        try:
            res = await bhavcopy.backfill(start, end, pause_seconds=1.5)
            log.info("backfill done: %s", res)
        except Exception as e:
            log.exception("backfill failed: %s", e)

    background.add_task(_runner)
    return {"ok": True, "queued": {"start": start.isoformat(),
                                    "end": end.isoformat()}}


@router.post("/option-history/backfill")
async def option_history_backfill(
    underlying: str,
    background: BackgroundTasks,
    history_back_days: int = Query(100, ge=1, le=100,
        description="Fyers caps at 100 days per call for 1-min resolution"),
    forward_weeklies: int = Query(2, ge=0, le=6),
    strikes_around_atm: int = Query(10, ge=1, le=20),
):
    """Backfill real 1-min option premium history for an underlying's
    ATM±N strikes across recent weekly expiries. Async — caller polls
    /option-history/status."""
    async def _runner():
        try:
            res = await option_history.backfill_underlying(
                underlying,
                history_back_days=history_back_days,
                forward_weeklies=forward_weeklies,
                strikes_around_atm=strikes_around_atm,
            )
            log.info("option-history backfill done: %s", res)
        except Exception as e:
            log.exception("option-history backfill failed: %s", e)
    background.add_task(_runner)
    return {"ok": True, "queued": {
        "underlying": underlying,
        "days": history_back_days,
        "forward_weeklies": forward_weeklies,
        "strikes": strikes_around_atm,
    }}


@router.get("/option-history/status")
async def option_history_status(
    underlying: str | None = Query(None),
    s: AsyncSession = Depends(get_session),
):
    """Coverage summary — rows + distinct contracts + ts range."""
    q = select(
        func.count(),
        func.min(OptionContract1m.ts),
        func.max(OptionContract1m.ts),
        func.count(func.distinct(OptionContract1m.symbol)),
        func.count(func.distinct(OptionContract1m.underlying)),
    )
    if underlying:
        q = q.where(OptionContract1m.underlying == underlying)
    n, mn, mx, contracts, unders = (await s.execute(q)).one()
    return {
        "rows": n,
        "earliest_ts": mn.isoformat() if mn else None,
        "latest_ts": mx.isoformat() if mx else None,
        "distinct_contracts": contracts,
        "distinct_underlyings": unders,
        "filter_underlying": underlying,
    }


@router.get("/bhavcopy/status")
async def bhavcopy_status(
    s: AsyncSession = Depends(get_session),
):
    """Coverage summary — earliest + latest date in option_eod, row count
    per year. Quick sanity check after a backfill."""
    total = (await s.execute(
        select(func.count()).select_from(OptionEod)
    )).scalar() or 0
    if total == 0:
        return {"rows": 0, "coverage": "empty"}

    earliest = (await s.execute(
        select(func.min(OptionEod.trade_date))
    )).scalar()
    latest = (await s.execute(
        select(func.max(OptionEod.trade_date))
    )).scalar()
    n_underlyings = (await s.execute(
        select(func.count(func.distinct(OptionEod.underlying)))
    )).scalar() or 0

    return {
        "rows": total,
        "earliest_date": earliest.isoformat() if earliest else None,
        "latest_date": latest.isoformat() if latest else None,
        "distinct_underlyings": n_underlyings,
    }
