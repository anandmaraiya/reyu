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
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db import SessionLocal, Instrument, Tick1m, OptionSnapshot, OptionStrikeSnapshot
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
    # SAFEGUARD: when Fyers is unauthed, fy.option_chain returns mock
    # data. Persisting that pollutes downstream charts + RL training
    # with bogus prices. Skip the entire poll when in demo mode — better
    # to lose a minute than store fake numbers.
    if await fy.is_demo():
        return
    # Chain fetch with 3-attempt exponential backoff. Fyers throttles
    # under burst load; without this, ~5-15 % of tier-1 polls return
    # empty during volatile periods and we lose that minute's snapshot
    # permanently (no historical chain endpoint to back-fill from).
    raw = None
    for attempt in range(3):
        try:
            raw = await fy.option_chain(symbol, 30)
            if raw:
                break
        except Exception as e:
            if attempt == 2:
                log.warning("chain %s failed after 3 attempts: %s", symbol, e)
                return
            await asyncio.sleep(0.8 * (2 ** attempt))      # 0.8s, 1.6s
    if raw is None:
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

    snap_ts = datetime.utcnow().replace(second=0, microsecond=0)
    async with SessionLocal() as s:
        stmt = pg_insert(OptionSnapshot).values(
            ts=snap_ts, symbol=symbol, expiry=expiry_dt,
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

        # Per-strike snapshot — ATM ± 15 strikes so future RL training has
        # real per-leg OI / IV / premium history (not just aggregates).
        # Widened from ±10 to ±15 to keep OTM8/OTM9 wing strikes inside
        # the visible band even when NIFTY drifts mid-day — the iron-
        # condor intraday replay was losing wing tracking with ±10.
        atm = summary.get("atm_strike")
        sorted_strikes = sorted(chain["strikes"], key=lambda r: r["strike"])
        atm_idx = next((i for i, r in enumerate(sorted_strikes) if r["strike"] == atm), -1)
        if atm_idx >= 0:
            window = sorted_strikes[max(0, atm_idx - 15): atm_idx + 16]
            for row in window:
                ce = row.get("ce") or {}
                pe = row.get("pe") or {}
                if not ce.get("symbol") and not pe.get("symbol"):
                    continue
                await s.execute(pg_insert(OptionStrikeSnapshot).values(
                    ts=snap_ts, underlying=symbol, strike=row["strike"], expiry=expiry_dt,
                    ce_oi=int(ce.get("oi") or 0),
                    ce_oi_change=int(ce.get("oi_change") or 0),
                    ce_volume=int(ce.get("volume") or 0),
                    ce_ltp=ce.get("ltp"), ce_iv=ce.get("iv"),
                    pe_oi=int(pe.get("oi") or 0),
                    pe_oi_change=int(pe.get("oi_change") or 0),
                    pe_volume=int(pe.get("volume") or 0),
                    pe_ltp=pe.get("ltp"), pe_iv=pe.get("iv"),
                    spot=chain["ltp"],
                ).on_conflict_do_nothing())

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
    """5-minute inference cycle — runs decisions across tier-1 universe.
    Skipped outside NSE trading hours (Mon–Fri 09:15–15:30 IST); the sweep
    cycle continues so any in-flight trades are still managed and
    eventually time out at close."""
    from app.rl.inference import decide_universe
    from app.rl.calendar import is_trading_hours
    if not is_trading_hours():
        log.debug("RL decide skipped — market closed")
        return
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


async def paper_live_cycle() -> None:
    """Every 60s during market hours, fire entries for PAPER_LIVE
    strategies + reconcile closed trades. Sprint 4.1."""
    from app.strategy.paper_live import cycle, reconcile_closed_trades
    try:
        await cycle()
        await reconcile_closed_trades()
    except Exception as e:
        log.exception("paper-live cycle failed: %s", e)


async def bhavcopy_daily_pull() -> None:
    """Daily NSE F&O Bhavcopy pull. NSE publishes around 17:30 IST; we
    fire at 18:00 IST (12:30 UTC) Mon-Fri to be safe. Idempotent — the
    fetcher UPSERTs, so a missed day picked up the next morning rewrites
    the same rows."""
    from app.data.bhavcopy import daily_pull_today
    await daily_pull_today()


async def fyers_eod_snapshot() -> None:
    """15:35 IST snapshot of Fyers orderBook / tradeBook / positions.
    These endpoints are current-day only — snapshot or lose forever."""
    from app.data.fyers_sync import snapshot_today
    try:
        res = await snapshot_today()
        log.info("fyers EOD snapshot: %s", res)
    except Exception as e:
        log.exception("fyers EOD snapshot failed: %s", e)


async def morning_batch_job() -> None:
    """08:00 IST data catch-up: Bhavcopy + option_contract_1m + tick_1m."""
    from app.data.morning_batch import run_morning_batch
    try:
        res = await run_morning_batch()
        log.info("morning batch: %s", res)
    except Exception as e:
        log.exception("morning batch failed: %s", e)


async def daily_options_history_job() -> None:
    """09:00 IST daily backfill of per-contract 1-min option history.

    Architecture (continuous dataset capture):
      * Indices (6):      7-day window, ATM±15 — small + critical
      * Top-10 stocks:    7-day window, ATM±10 — second priority
    Total ~10-15 minutes of Fyers calls. Re-runs are idempotent (UPSERT
    on conflict do nothing); the existing rows stay, only new minutes
    land.

    The heavier 100-day backfill happens (a) auto-fired on Fyers OAuth
    callback, (b) weekly via weekly_long_backfill_job (Sunday 04:00 IST
    when market is closed and the event loop is free).
    """
    from app.data import option_history
    from app.fyers import client as fy

    if await fy.is_demo():
        log.info("daily options history: skipped — Fyers in demo mode")
        return

    indices = [
        "NSE:NIFTY50-INDEX",
        "NSE:NIFTYBANK-INDEX",
        "NSE:FINNIFTY-INDEX",
        "NSE:MIDCPNIFTY-INDEX",
    ]
    top_stocks = [
        "NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ", "NSE:ICICIBANK-EQ",
        "NSE:INFY-EQ", "NSE:TCS-EQ", "NSE:SBIN-EQ",
        "NSE:BHARTIARTL-EQ", "NSE:AXISBANK-EQ",
        "NSE:KOTAKBANK-EQ", "NSE:LT-EQ",
    ]
    out: dict = {}
    for u in indices + top_stocks:
        try:
            r = await option_history.backfill_underlying(
                u, history_back_days=7,
                forward_weeklies=2,
                strikes_around_atm=15 if "INDEX" in u else 10,
                polite_delay_sec=0.3,
            )
            out[u] = {
                "ins": r.get("candles_inserted"),
                "tainted": r.get("contracts_tainted_spot_substitution"),
                "dead": r.get("contracts_dead_before_window"),
                "fail": r.get("contracts_failed"),
            }
        except Exception as e:
            out[u] = {"error": str(e)}
            log.exception("daily options history %s failed", u)
    total_inserted = sum(v.get("ins", 0) for v in out.values() if isinstance(v, dict))
    log.info("daily options history: %d candles across %d underlyings | %s",
             total_inserted, len(out), out)


async def weekly_long_backfill_job() -> None:
    """Sunday 04:00 IST — heavy 100-day backfill across full universe.

    Market is closed (Sun = weekend), so the per-minute snapshot poller
    isn't competing for Fyers throughput. ~30-60 min runtime depending
    on Fyers latency.

    Idempotent — existing candles aren't overwritten.
    """
    from app.data import option_history
    from app.fyers import client as fy

    if await fy.is_demo():
        log.info("weekly long backfill: skipped — Fyers in demo mode")
        return

    targets = [
        "NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX", "NSE:FINNIFTY-INDEX",
        "NSE:MIDCPNIFTY-INDEX",
        "NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ", "NSE:ICICIBANK-EQ",
        "NSE:INFY-EQ", "NSE:TCS-EQ", "NSE:SBIN-EQ",
        "NSE:BHARTIARTL-EQ", "NSE:AXISBANK-EQ", "NSE:KOTAKBANK-EQ",
        "NSE:LT-EQ", "NSE:ITC-EQ", "NSE:HINDUNILVR-EQ",
        "NSE:BAJFINANCE-EQ", "NSE:MARUTI-EQ", "NSE:M&M-EQ",
        "NSE:TATAMOTORS-EQ",
    ]
    total = 0
    for u in targets:
        try:
            r = await option_history.backfill_underlying(
                u, history_back_days=100,
                forward_weeklies=2,
                strikes_around_atm=15 if "INDEX" in u else 10,
                polite_delay_sec=0.3,
            )
            total += r.get("candles_inserted", 0)
            log.info("weekly long backfill %s: +%d candles", u,
                     r.get("candles_inserted", 0))
        except Exception as e:
            log.exception("weekly long backfill %s failed", u)
    log.info("weekly long backfill: total %d new candles across %d underlyings",
             total, len(targets))


async def regime_router_morning_job() -> None:
    """09:25 IST — regime-router classifies + opens paper trade for today."""
    from app.strategy.regime_router_live import morning_decision
    try:
        res = await morning_decision()
        log.info("regime-router morning: %s", res)
    except Exception as e:
        log.exception("regime-router morning failed: %s", e)


async def regime_router_close_job() -> None:
    """15:20 IST — close every OPEN regime-router paper trade."""
    from app.strategy.regime_router_live import eod_close
    try:
        res = await eod_close()
        log.info("regime-router close: %s", res)
    except Exception as e:
        log.exception("regime-router close failed: %s", e)


async def onboarding_drip_job() -> None:
    """Runs daily 03:00 UTC (~08:30 IST). Sends drip emails to users at
    day 1, 3, 7 post-signup. Idempotent — never sends the same template
    twice per user."""
    from datetime import datetime, timedelta
    from sqlalchemy import select, text
    from app.db import SessionLocal, User
    from app.notify_email import send_email, drip_day1_html, drip_day3_html, drip_day7_html
    from app.config import settings

    templates = [
        (1, "drip_day1", drip_day1_html, "See live signals — connect your broker"),
        (3, "drip_day3", drip_day3_html, "Test a strategy in 30 seconds"),
        (7, "drip_day7", drip_day7_html, "A week in — here's what's running for you"),
    ]
    now = datetime.utcnow()
    sent_counts = {}
    async with SessionLocal() as s:
        for day_offset, template_name, template_fn, subject in templates:
            window_start = now - timedelta(days=day_offset, hours=12)
            window_end = now - timedelta(days=day_offset - 1)
            # Users signed up within the target window who haven't received this template
            q = text("""
                SELECT u.id, u.email, u.display_name
                FROM users u
                LEFT JOIN user_email_events e
                  ON e.user_id = u.id AND e.template = :template
                WHERE u.created_at BETWEEN :start AND :end
                  AND u.is_active = TRUE
                  AND e.user_id IS NULL
            """)
            rows = (await s.execute(q, {
                "template": template_name,
                "start": window_start,
                "end": window_end,
            })).fetchall()

            for row in rows:
                display = row.display_name or row.email.split("@")[0]
                try:
                    await send_email(
                        to=row.email,
                        subject=subject,
                        html=template_fn(display, settings.frontend_url),
                    )
                    await s.execute(text(
                        "INSERT INTO user_email_events (user_id, template) "
                        "VALUES (:uid, :tpl) ON CONFLICT DO NOTHING"
                    ), {"uid": row.id, "tpl": template_name})
                except Exception as e:
                    log.exception("drip %s failed for %s: %s", template_name, row.email, e)
            sent_counts[template_name] = len(rows)
        await s.commit()
    log.info("onboarding drip: %s", sent_counts)


async def dataset_health_check() -> None:
    """Daily 07:30 IST log — what did we capture yesterday across each table.

    Lets a glance at the logs confirm the dataset is growing. A sudden
    drop in any counter is the canary for Fyers auth/quota issues.
    """
    try:
        from sqlalchemy import select, func
        from app.db import SessionLocal, OptionContract1m, OptionStrikeSnapshot, Tick1m
        async with SessionLocal() as s:
            counts = {}
            for label, model, ts_col in [
                ("option_contract_1m", OptionContract1m, OptionContract1m.ts),
                ("option_strike_snapshot", OptionStrikeSnapshot, OptionStrikeSnapshot.ts),
                ("tick_1m", Tick1m, Tick1m.ts),
            ]:
                total = (await s.execute(select(func.count()).select_from(model))).scalar()
                latest = (await s.execute(select(func.max(ts_col)))).scalar()
                counts[label] = {"rows": total, "latest": latest.isoformat() if latest else None}
        log.info("dataset health: %s", counts)
    except Exception as e:
        log.exception("dataset health check failed: %s", e)


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
    # Paper-live strategies — 60s cadence during market hours
    scheduler.add_job(paper_live_cycle, "interval", seconds=60,
                      id="paper_live", max_instances=1, coalesce=True)
    # NSE Bhavcopy — 18:00 IST = 12:30 UTC, Mon-Fri
    scheduler.add_job(bhavcopy_daily_pull,
                      CronTrigger(day_of_week="mon-fri", hour=12, minute=30),
                      id="bhavcopy_daily", max_instances=1, coalesce=True)
    # Fyers EOD snapshot — 15:35 IST = 10:05 UTC, Mon-Fri (must run before rollover)
    scheduler.add_job(fyers_eod_snapshot,
                      CronTrigger(day_of_week="mon-fri", hour=10, minute=5),
                      id="fyers_eod_snapshot", max_instances=1, coalesce=True)
    # Morning batch — 08:00 IST = 02:30 UTC, Mon-Fri (pre-market catch-up)
    scheduler.add_job(morning_batch_job,
                      CronTrigger(day_of_week="mon-fri", hour=2, minute=30),
                      id="morning_batch", max_instances=1, coalesce=True)
    # Daily options-1m history — 09:00 IST = 03:30 UTC, Mon-Fri
    # Runs JUST BEFORE 09:15 IST market open so live-week contracts have
    # fresh per-strike intraday data. Covers 4 indices + top-10 stocks.
    scheduler.add_job(daily_options_history_job,
                      CronTrigger(day_of_week="mon-fri", hour=3, minute=30),
                      id="daily_options_history", max_instances=1, coalesce=True)
    # Weekly long backfill — Sunday 04:00 IST = Sat 22:30 UTC. Market is
    # closed, no contention with the per-minute poller. Heavy 100-day
    # pull across 20 underlyings — keeps the dataset filled out.
    scheduler.add_job(weekly_long_backfill_job,
                      CronTrigger(day_of_week="sun", hour=4, minute=0),
                      id="weekly_long_backfill", max_instances=1, coalesce=True)
    # Dataset health check — 07:30 IST = 02:00 UTC daily. Logs rowcounts
    # per table so a glance at logs confirms the dataset is growing.
    scheduler.add_job(dataset_health_check,
                      CronTrigger(hour=2, minute=0),
                      id="dataset_health", max_instances=1, coalesce=True)
    # Onboarding drip emails — 08:30 IST = 03:00 UTC daily. Sends day 1,
    # 3, 7 nudges to eligible users. Idempotent via user_email_events.
    scheduler.add_job(onboarding_drip_job,
                      CronTrigger(hour=3, minute=0),
                      id="onboarding_drip", max_instances=1, coalesce=True)
    # Regime-router morning decision — 09:25 IST = 03:55 UTC, Mon-Fri.
    # 5 min before market open so legs price off the most recent snapshot.
    scheduler.add_job(regime_router_morning_job,
                      CronTrigger(day_of_week="mon-fri", hour=3, minute=55),
                      id="regime_router_morning", max_instances=1, coalesce=True)
    # Regime-router EOD close — 15:20 IST = 09:50 UTC, Mon-Fri.
    # 10 min before market close to avoid the closing-auction chaos.
    scheduler.add_job(regime_router_close_job,
                      CronTrigger(day_of_week="mon-fri", hour=9, minute=50),
                      id="regime_router_close", max_instances=1, coalesce=True)
    scheduler.start()
    log.info("scheduler started — high every %ds, low every %ds, RL decide 300s, "
             "RL sweep 60s, Bhavcopy 18:00 IST Mon-Fri",
             settings.snapshot_interval_sec, max(settings.snapshot_interval_sec * 5, 300))


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
