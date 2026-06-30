"""Data-lake admin endpoints -- Sprint 0.2."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, OptionEod, OptionContract1m, Tick1m, FyersOrder, FyersTrade, FyersPosition
from app.data import bhavcopy, option_history, fyers_sync, morning_batch

router = APIRouter()
log = logging.getLogger("reyu.routers.data_lake")


@router.post("/bhavcopy/fetch")
async def bhavcopy_fetch_one(target_date: date = Query(..., alias="date")):
    """Pull + ingest a single date. Synchronous (~2-5s)."""
    return await bhavcopy.fetch_one(target_date)


@router.post("/bhavcopy/backfill")
async def bhavcopy_backfill(start: date, end: date, background: BackgroundTasks):
    """Multi-day backfill in background -- poll /status."""
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
    return {"ok": True, "queued": {"start": start.isoformat(), "end": end.isoformat()}}


@router.post("/option-history/backfill")
async def option_history_backfill(
    underlying: str,
    background: BackgroundTasks,
    history_back_days: int = Query(100, ge=1, le=100),
    forward_weeklies: int = Query(2, ge=0, le=6),
    strikes_around_atm: int = Query(10, ge=1, le=20),
):
    """Backfill 1-min option premium history for ATM+/-N strikes. Async."""
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
        "underlying": underlying, "days": history_back_days,
        "forward_weeklies": forward_weeklies, "strikes": strikes_around_atm,
    }}


@router.get("/option-history/status")
async def option_history_status(
    underlying: str | None = Query(None),
    s: AsyncSession = Depends(get_session),
):
    """Coverage summary -- rows + distinct contracts + ts range."""
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
    """Snapshot Fyers orderBook + tradeBook + positions RIGHT NOW."""
    return await fyers_sync.snapshot_today()


@router.post("/option-history/backfill-all-now")
async def backfill_all_now(
    background: BackgroundTasks,
    history_back_days: int = Query(100, ge=1, le=100),
    forward_weeklies: int = Query(2, ge=0, le=6),
    strikes_around_atm: int = Query(15, ge=1, le=20),
):
    """Trigger backfill for ALL tier-1 underlyings immediately. Same call
    the OAuth callback fires after Fyers login — use this to re-run if
    a previous backfill was killed mid-flight."""
    targets = [
        "NSE:NIFTY50-INDEX",
        "NSE:NIFTYBANK-INDEX",
        "NSE:FINNIFTY-INDEX",
    ]
    async def _runner():
        for u in targets:
            try:
                res = await option_history.backfill_underlying(
                    u, history_back_days=history_back_days,
                    forward_weeklies=forward_weeklies,
                    strikes_around_atm=strikes_around_atm,
                    polite_delay_sec=0.3,
                )
                log.info("backfill-all-now %s: %s", u, res)
            except Exception as e:
                log.exception("backfill-all-now %s failed: %s", u, e)
    background.add_task(_runner)
    return {"ok": True, "queued": targets,
            "params": {"days": history_back_days,
                       "weeklies": forward_weeklies,
                       "strikes": strikes_around_atm}}


@router.get("/fyers/state")
async def fyers_state(
    target_date: str | None = Query(None, alias="date"),
    s: AsyncSession = Depends(get_session),
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
        "orders": [{"order_id": o.order_id, "symbol": o.symbol, "side": o.side,
            "qty": o.qty, "filled_qty": o.filled_qty, "status": o.status,
            "avg_price": o.avg_price,
            "order_ts": o.order_ts.isoformat() if o.order_ts else None} for o in orders],
        "trades": [{"order_id": t.order_id, "symbol": t.symbol, "side": t.side,
            "qty": t.qty, "price": t.price, "trade_value": t.trade_value,
            "trade_ts": t.trade_ts.isoformat() if t.trade_ts else None} for t in trades],
        "positions": [{"symbol": p.symbol, "net_qty": p.net_qty,
            "buy_avg": p.buy_avg, "sell_avg": p.sell_avg,
            "realized_pnl": p.realized_pnl, "unrealized_pnl": p.unrealized_pnl,
            "ltp": p.ltp} for p in positions],
    }


@router.post("/morning-batch")
async def trigger_morning_batch(background: BackgroundTasks):
    """Manually fire the 08:00 IST morning batch."""
    async def _runner():
        try:
            res = await morning_batch.run_morning_batch()
            log.info("morning batch (manual): %s", res)
        except Exception as e:
            log.exception("morning batch (manual) failed: %s", e)
    background.add_task(_runner)
    return {"ok": True, "queued": True}


@router.get("/bhavcopy/status")
async def bhavcopy_status(s: AsyncSession = Depends(get_session)):
    """Coverage summary -- earliest + latest date in option_eod."""
    total = (await s.execute(select(func.count()).select_from(OptionEod))).scalar() or 0
    if total == 0:
        return {"rows": 0, "coverage": "empty"}
    earliest = (await s.execute(select(func.min(OptionEod.trade_date)))).scalar()
    latest = (await s.execute(select(func.max(OptionEod.trade_date)))).scalar()
    n_underlyings = (await s.execute(
        select(func.count(func.distinct(OptionEod.underlying)))
    )).scalar() or 0
    return {
        "rows": total,
        "earliest_date": earliest.isoformat() if earliest else None,
        "latest_date": latest.isoformat() if latest else None,
        "distinct_underlyings": n_underlyings,
    }


# ---------------------------------------------------------------------------
# Unified status -- one call to see ALL data coverage
# ---------------------------------------------------------------------------

@router.get("/status")
async def data_status(s: AsyncSession = Depends(get_session)):
    """One-call coverage report for ALL data types."""
    from app.fyers import client as fy
    fyers_live = not await fy.is_demo()

    bhav_total = (await s.execute(select(func.count()).select_from(OptionEod))).scalar() or 0
    bhav_min = (await s.execute(select(func.min(OptionEod.trade_date)))).scalar()
    bhav_max = (await s.execute(select(func.max(OptionEod.trade_date)))).scalar()

    oc_total = (await s.execute(select(func.count()).select_from(OptionContract1m))).scalar() or 0
    oc_min = (await s.execute(select(func.min(OptionContract1m.ts)))).scalar()
    oc_max = (await s.execute(select(func.max(OptionContract1m.ts)))).scalar()
    oc_contracts = (await s.execute(
        select(func.count(func.distinct(OptionContract1m.symbol)))
    )).scalar() or 0

    tick_total = (await s.execute(select(func.count()).select_from(Tick1m))).scalar() or 0
    tick_min = (await s.execute(select(func.min(Tick1m.ts)))).scalar()
    tick_max = (await s.execute(select(func.max(Tick1m.ts)))).scalar()
    tick_syms = (await s.execute(
        select(func.count(func.distinct(Tick1m.symbol)))
    )).scalar() or 0

    snap_dates = (await s.execute(
        select(func.count(func.distinct(FyersPosition.snapshot_date)))
    )).scalar() or 0

    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    return {
        "checked_at": now_ist.isoformat(),
        "fyers_connected": fyers_live,
        "bhavcopy": {
            "rows": bhav_total,
            "from": bhav_min.isoformat() if bhav_min else None,
            "to": bhav_max.isoformat() if bhav_max else None,
            "status": "ok" if bhav_total > 0 else "empty -- POST /api/data/bhavcopy/backfill",
        },
        "option_candles_1m": {
            "rows": oc_total,
            "contracts": oc_contracts,
            "from": oc_min.isoformat() if oc_min else None,
            "to": oc_max.isoformat() if oc_max else None,
            "status": (
                "ok" if oc_total > 0
                else ("needs Fyers auth first" if not fyers_live
                      else "empty -- POST /api/data/option-history/backfill")
            ),
        },
        "spot_candles_1m": {
            "rows": tick_total,
            "symbols": tick_syms,
            "from": tick_min.isoformat() if tick_min else None,
            "to": tick_max.isoformat() if tick_max else None,
            "status": "ok" if tick_total > 0 else "empty -- scheduler fills on first market poll",
        },
        "fyers_eod_snapshots": {
            "snapshot_days": snap_dates,
            "status": "ok" if snap_dates > 0 else "empty -- fires at 15:35 IST weekdays",
        },
        "scheduled_jobs": {
            "morning_batch": "08:00 IST Mon-Fri -- Bhavcopy + option_contract_1m + tick_1m",
            "daily_options_history": "09:00 IST Mon-Fri -- option_contract_1m 7-day refresh",
            "bhavcopy_daily": "18:00 IST Mon-Fri -- today Bhavcopy",
            "fyers_eod_snapshot": "15:35 IST Mon-Fri -- orders/trades/positions",
            "poll_high": "every 60s market hours -- tick_1m + option snapshots",
        },
    }


# ---------------------------------------------------------------------------
# Full initial backfill -- run once on a fresh VM
# ---------------------------------------------------------------------------

BACKFILL_UNDERLYINGS = [
    "NSE:NIFTY50-INDEX",
    "NSE:NIFTYBANK-INDEX",
    "NSE:FINNIFTY-INDEX",
]


@router.post("/full-backfill")
async def full_backfill(
    background: BackgroundTasks,
    bhavcopy_years: int = Query(3, ge=1, le=12,
        description="Years of Bhavcopy EOD data to pull"),
    option_days: int = Query(100, ge=7, le=100,
        description="Days of 1-min option candle history via Fyers (Fyers cap=100)"),
    strikes_around_atm: int = Query(10, ge=5, le=20),
):
    """One-shot backfill for a fresh deployment.

    Steps (queued in background):
      1. Bhavcopy EOD -- NSE archives, no Fyers needed
      2. option_contract_1m -- Fyers 1-min bars, requires Fyers auth
      3. tick_1m spot history -- Fyers, requires Fyers auth

    Fyers steps are auto-skipped if not authenticated.
    Poll GET /api/data/status to track progress.
    """
    from app.fyers import client as fy

    end_date = date.today()
    start_date = date(end_date.year - bhavcopy_years, end_date.month, end_date.day)

    async def _runner():
        log.info("=== FULL BACKFILL START ===")

        # Step 1: Bhavcopy -- no Fyers needed
        log.info("Step 1/3: Bhavcopy %s -> %s", start_date, end_date)
        try:
            res = await bhavcopy.backfill(start_date, end_date, pause_seconds=1.2)
            log.info("Bhavcopy done: %s", res)
        except Exception as e:
            log.exception("Bhavcopy backfill failed: %s", e)

        # Steps 2+3 require Fyers
        if await fy.is_demo():
            log.warning(
                "Steps 2+3 skipped -- Fyers not authenticated. "
                "POST /api/auth/set-token then re-trigger /full-backfill."
            )
            return

        # Step 2: Intraday option candles
        log.info("Step 2/3: option_contract_1m %d underlyings x %d days",
                 len(BACKFILL_UNDERLYINGS), option_days)
        for u in BACKFILL_UNDERLYINGS:
            try:
                r = await option_history.backfill_underlying(
                    u,
                    history_back_days=option_days,
                    forward_weeklies=2,
                    strikes_around_atm=strikes_around_atm,
                    polite_delay_sec=0.4,
                )
                log.info("option_history %s: inserted=%s failed=%s",
                         u, r.get("candles_inserted"), r.get("contracts_failed"))
            except Exception as e:
                log.exception("option_history %s failed: %s", u, e)

        # Step 3: Spot 1m history via cache (fetches Fyers + upserts tick_1m)
        from app.fyers.cache import get_candles
        log.info("Step 3/3: spot tick_1m for index symbols")
        today_str = str(date.today())
        start_str = str(date.today() - timedelta(days=option_days))
        for sym in BACKFILL_UNDERLYINGS:
            try:
                r = await get_candles(sym, "1", start_str, today_str)
                log.info("tick_1m %s: %d candles", sym, len(r.get("candles", [])))
            except Exception as e:
                log.exception("tick_1m %s failed: %s", sym, e)

        log.info("=== FULL BACKFILL COMPLETE ===")

    background.add_task(_runner)
    return {
        "ok": True,
        "queued": {
            "bhavcopy_range": "%s -> %s" % (start_date, end_date),
            "option_days": option_days,
            "underlyings": BACKFILL_UNDERLYINGS,
            "note": "Fyers steps skipped if not authenticated",
        },
        "monitor": "GET /api/data/status",
    }
