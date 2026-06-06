"""APScheduler-driven background poller.

Two tiers:
  tier=1 (high priority): polled every 60 seconds  — indices + top-30 stocks
  tier=2 (low priority):  polled every 5 minutes   — broader F&O universe

Per-tier polls run as one APScheduler job and dispatch symbols concurrently
through an asyncio.Semaphore so we don't hammer Fyers serially. With ~30
high-priority symbols and a concurrency of 10, a poll loop finishes well
inside 60 seconds.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db import SessionLocal, Instrument, Tick1m, OptionSnapshot
from app.fyers import client as fy
from app.fno_universe import all_high_priority, all_low_priority
from app.analytics.chain import normalize_chain, trade_bias
from app.store import store

log = logging.getLogger("reyu.scheduler")
scheduler = AsyncIOScheduler()

# Concurrent fetches per tier — tuned so a tier completes in well under its
# polling interval. Adjust if you see Fyers rate-limit responses.
HIGH_CONCURRENCY = 10
LOW_CONCURRENCY = 5


async def seed_tracked() -> None:
    """Ensure the full F&O universe is in `instruments` with tracked=1.

    High-priority + env-listed symbols get tier=1; everything else tier=2.
    Idempotent: re-running just re-applies tracked/tier.
    """
    env_extras = [x.strip() for x in settings.tracked_symbols.split(",") if x.strip()]
    tier1 = set(all_high_priority()) | set(env_extras)
    tier2 = set(all_low_priority()) - tier1

    async with SessionLocal() as s:
        for sym in tier1:
            await s.execute(pg_insert(Instrument).values(
                symbol=sym, tracked=1, tier=1
            ).on_conflict_do_update(
                index_elements=[Instrument.symbol], set_={"tracked": 1, "tier": 1}
            ))
        for sym in tier2:
            await s.execute(pg_insert(Instrument).values(
                symbol=sym, tracked=1, tier=2
            ).on_conflict_do_update(
                index_elements=[Instrument.symbol], set_={"tracked": 1, "tier": 2}
            ))
        await s.commit()
    log.info("seeded tracked symbols — tier1=%d tier2=%d", len(tier1), len(tier2))


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
        for c in candles[-5:]:
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


async def _poll_one(sym: str, sem: asyncio.Semaphore) -> None:
    async with sem:
        try:
            await _save_tick(sym)
            await _save_snapshot(sym)
        except Exception as e:
            log.exception("poll %s failed: %s", sym, e)


async def _poll_tier(tier: int, concurrency: int) -> None:
    start = datetime.utcnow()
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(Instrument).where(Instrument.tracked == 1, Instrument.tier == tier)
        )).scalars().all()
    if not rows:
        return
    sem = asyncio.Semaphore(concurrency)
    await asyncio.gather(*[_poll_one(r.symbol, sem) for r in rows])
    elapsed = (datetime.utcnow() - start).total_seconds()
    log.info("tier-%d polled %d symbols in %.1fs", tier, len(rows), elapsed)
    await store.r.set(f"poll:last:{tier}", datetime.utcnow().isoformat(), ex=24 * 3600)


async def poll_high() -> None:
    await _poll_tier(1, HIGH_CONCURRENCY)


async def poll_low() -> None:
    await _poll_tier(2, LOW_CONCURRENCY)


async def poll_all() -> None:
    """Back-compat: kicked off once on startup so tier-2 gets seeded data."""
    await poll_high()
    await poll_low()


async def rl_decide_cycle() -> None:
    """5-minute inference cycle — runs decisions across tier-1 universe."""
    from app.rl.inference import decide_universe
    try:
        results = await decide_universe()
    except Exception as e:
        log.exception("RL decide cycle failed: %s", e)
        return
    opened = sum(1 for r in results if r.get("trade_id"))
    log.info("RL decide cycle: %d symbols scanned, %d trades opened", len(results), opened)


async def rl_sweep_cycle() -> None:
    """1-minute sweep — close TP/SL hits on open RL trades + nightly train."""
    from app.rl.env import sweep_open_trades
    from app.rl.trainer import train_on_closed_trades
    async with SessionLocal() as s:
        try:
            res = await sweep_open_trades(s)
            if res["tp"] + res["sl"] + res["timeout"] > 0:
                log.info("RL sweep: %s", res)
                # Train immediately on freshly closed trades
                await train_on_closed_trades(s)
        except Exception as e:
            log.exception("RL sweep failed: %s", e)


def start() -> None:
    scheduler.add_job(poll_high, "interval", seconds=settings.snapshot_interval_sec,
                      id="poll_high", max_instances=1, coalesce=True)
    scheduler.add_job(poll_low, "interval", seconds=max(settings.snapshot_interval_sec * 5, 300),
                      id="poll_low", max_instances=1, coalesce=True)
    # RL cycles — 5-minute decisions, 1-minute bracket sweep
    scheduler.add_job(rl_decide_cycle, "interval", seconds=300,
                      id="rl_decide", max_instances=1, coalesce=True)
    scheduler.add_job(rl_sweep_cycle, "interval", seconds=60,
                      id="rl_sweep", max_instances=1, coalesce=True)
    scheduler.start()
    log.info("scheduler started — high every %ds, low every %ds, RL decide 300s, RL sweep 60s",
             settings.snapshot_interval_sec, max(settings.snapshot_interval_sec * 5, 300))


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
