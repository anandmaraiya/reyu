"""APScheduler-driven 1-minute poller.

For every symbol in `instruments.tracked=1` (seeded from TRACKED_SYMBOLS env),
we pull:
  - latest 1-min candle  -> tick_1m
  - option chain         -> option_snapshot (PCR / OI / max-pain / atm IV)

On each poll we also push the latest snapshot into Redis pub/sub channel
`ticks:<symbol>` so the WebSocket fanout can deliver it to subscribers.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db import SessionLocal, Instrument, Tick1m, OptionSnapshot
from app.fyers import client as fy
from app.analytics.chain import normalize_chain, trade_bias
from app.store import store

log = logging.getLogger("reyu.scheduler")
scheduler = AsyncIOScheduler()


async def seed_tracked() -> None:
    """Ensure each TRACKED_SYMBOLS row exists with tracked=1."""
    async with SessionLocal() as s:
        for sym in [x.strip() for x in settings.tracked_symbols.split(",") if x.strip()]:
            stmt = pg_insert(Instrument).values(symbol=sym, tracked=1).on_conflict_do_update(
                index_elements=[Instrument.symbol], set_={"tracked": 1}
            )
            await s.execute(stmt)
        await s.commit()


async def _save_tick(symbol: str) -> None:
    today = datetime.utcnow().date()
    try:
        hist = await fy.history(
            symbol, resolution="1",
            range_from=str(today - timedelta(days=1)), range_to=str(today),
        )
    except Exception as e:
        log.warning("history %s failed: %s", symbol, e)
        return
    candles = hist.get("candles", []) if isinstance(hist, dict) else []
    if not candles:
        return
    async with SessionLocal() as s:
        for c in candles[-5:]:  # upsert last 5 candles to catch late prints
            ts = datetime.utcfromtimestamp(c[0])
            stmt = pg_insert(Tick1m).values(
                ts=ts, symbol=symbol, open=c[1], high=c[2], low=c[3], close=c[4],
                volume=int(c[5] or 0), oi=int(c[6] or 0) if len(c) > 6 else 0,
            ).on_conflict_do_update(
                index_elements=[Tick1m.ts, Tick1m.symbol],
                set_={"open": c[1], "high": c[2], "low": c[3], "close": c[4],
                      "volume": int(c[5] or 0)},
            )
            await s.execute(stmt)
        await s.commit()

    last = candles[-1]
    await store.r.publish(f"ticks:{symbol}", json.dumps({
        "symbol": symbol, "ts": last[0], "close": last[4], "volume": last[5],
    }))


async def _save_snapshot(symbol: str) -> None:
    try:
        raw = await fy.option_chain(symbol, 30)
    except Exception as e:
        log.warning("chain %s failed: %s", symbol, e)
        return
    chain = normalize_chain(raw)
    if not chain.get("strikes"):
        return
    bias = trade_bias(chain["summary"])
    summary = chain["summary"]
    expiry_ts = chain.get("expiry")
    try:
        expiry_dt = datetime.utcfromtimestamp(int(expiry_ts)) if expiry_ts else datetime.utcnow()
    except Exception:
        expiry_dt = datetime.utcnow()

    async with SessionLocal() as s:
        stmt = pg_insert(OptionSnapshot).values(
            ts=datetime.utcnow().replace(second=0, microsecond=0),
            symbol=symbol, expiry=expiry_dt,
            ltp=chain["ltp"],
            pcr_oi=summary.get("pcr_oi") or 0,
            pcr_volume=summary.get("pcr_volume") or 0,
            max_pain=summary.get("max_pain") or 0,
            atm_strike=summary.get("atm_strike") or 0,
            atm_iv=summary.get("atm_iv") or 0,
            total_ce_oi=int(summary.get("total_ce_oi") or 0),
            total_pe_oi=int(summary.get("total_pe_oi") or 0),
            ce_oi_change=int(summary.get("ce_oi_change") or 0),
            pe_oi_change=int(summary.get("pe_oi_change") or 0),
            bias_score=bias["score"],
        ).on_conflict_do_nothing()
        await s.execute(stmt)
        await s.commit()

    await store.r.publish(f"chain:{symbol}", json.dumps({
        "symbol": symbol, "summary": summary, "bias": bias, "ltp": chain["ltp"],
    }, default=str))


async def poll_all() -> None:
    async with SessionLocal() as s:
        rows = (await s.execute(select(Instrument).where(Instrument.tracked == 1))).scalars().all()
    log.info("polling %d tracked symbols", len(rows))
    for inst in rows:
        try:
            await _save_tick(inst.symbol)
            await _save_snapshot(inst.symbol)
        except Exception as e:
            log.exception("poll %s failed: %s", inst.symbol, e)


def start() -> None:
    scheduler.add_job(poll_all, "interval", seconds=settings.snapshot_interval_sec,
                      id="poll_all", max_instances=1, coalesce=True)
    scheduler.start()


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
