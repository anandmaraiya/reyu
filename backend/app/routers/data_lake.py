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

from app.db import get_session, OptionEod, OptionContract1m, FyersOrder, FyersTrade, FyersPosition
from sqlalchemy import select, func, desc
from app.data import bhavcopy, option_history, fyers_sync, morning_batch

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


@router.post("/fyers/snapshot")
async def fyers_snapshot_now():
    """Snapshot Fyers orderBook + tradeBook + positions RIGHT NOW.
    Manually trigger before market close or end-of-day if the cron missed."""
    res = await fyers_sync.snapshot_today()
    return res


@router.get("/fyers/state")
async def fyers_state(
    target_date: str | None = Query(None, alias="date",
        description="ISO date; defaults to most recent snapshot"),
    s = Depends(get_session),
):
    """List Fyers orders / trades / positions for a snapshot date."""
    from datetime import datetime as _dt
    if target_date:
        d = _dt.strptime(target_date, "%Y-%m-%d")
    else:
        d = (await s.execute(select(func.max(FyersPosition.snapshot_date)))).scalar()
        if d is None:
            d = (await s.execute(select(func.max(FyersOrder.snapshot_date)))).scalar()
    if d is None:
        return {"snapshot_date": None, "orders": [], "trades": [], "positions": []}
    orders = (await s.execute(
        select(FyersOrder).where(FyersOrder.snapshot_date == d)
        .order_by(desc(FyersOrder.order_ts)).limit(200)
    )).scalars().all()
    trades = (await s.execute(
        select(FyersTrade).where(FyersTrade.snapshot_date == d)
        .order_by(desc(FyersTrade.trade_ts)).limit(200)
    )).scalars().all()
    positions = (await s.execute(
        select(FyersPosition).where(FyersPosition.snapshot_date == d)
    )).scalars().all()
    return {
        "snapshot_date": d.isoformat(),
        "orders": [{
            "order_id": o.order_id, "symbol": o.symbol, "side": o.side,
            "qty": o.qty, "filled_qty": o.filled_qty, "remaining_qty": o.remaining_qty,
            "status": o.status, "limit_price": o.limit_price,
            "avg_price": o.avg_price,
            "order_ts": o.order_ts.isoformat() if o.order_ts else None,
        } for o in orders],
        "trades": [{
            "order_id": t.order_id, "trade_number": t.trade_number,
            "symbol": t.symbol, "side": t.side,
            "qty": t.qty, "price": t.price, "trade_value": t.trade_value,
            "trade_ts": t.trade_ts.isoformat() if t.trade_ts else None,
        } for t in trades],
        "positions": [{
            "symbol": p.symbol, "product_type": p.product_type,
            "net_qty": p.net_qty, "buy_qty": p.buy_qty, "sell_qty": p.sell_qty,
            "buy_avg": p.buy_avg, "sell_avg": p.sell_avg,
            "realized_pnl": p.realized_pnl, "unrealized_pnl": p.unrealized_pnl,
            "ltp": p.ltp,
        } for p in positions],
    }


@router.post("/morning-batch")
async def trigger_morning_batch(background: BackgroundTasks):
    """Manually fire the 08:00 IST morning batch — Bhavcopy yesterday,
    option_contract_1m for tracked underlyings, spot 1m history."""
    async def _runner():
        try:
            res = await morning_batch.run_morning_batch()
            log.info("morning batch (manual): %s", res)
        except Exception as e:
            log.exception("morning batch (manual) failed: %s", e)
    background.add_task(_runner)
    return {"ok": True, "queued": True}


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
