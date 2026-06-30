"""Operator-only data pipeline endpoints (superadmin gated).

Three concerns:

1. /test-fyers-pipeline  — comprehensive health check: Fyers auth, history
                           API, symbol enumeration, guard behaviour, real
                           insertion. Run this any time you suspect data
                           isn't landing.

2. /run-job              — trigger any scheduled job on-demand (avoids
                           waiting for the daily cron when verifying a
                           fix).

3. /daily-fills          — per-day rowcount per table, last N days. Powers
                           the frontend dataset-growth dashboard.

All endpoints require the `algo@reyu.ai` superadmin login.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, text

from app.db import (
    SessionLocal, OptionContract1m, OptionStrikeSnapshot, Tick1m, OptionEod,
)
from app.routers.user_auth import require_superadmin

log = logging.getLogger("reyu.admin_data")
router = APIRouter(prefix="/api/admin/data", tags=["admin-data"])


# ── 1. PIPELINE TEST ──────────────────────────────────────────────────
@router.post("/test-fyers-pipeline")
async def test_fyers_pipeline(
    underlying: str = Query("NSE:NIFTY50-INDEX"),
    history_back_days: int = Query(7, ge=1, le=30),
    _user: dict = Depends(require_superadmin),
):
    """End-to-end pipeline probe.

    Steps:
      1. Fyers auth status
      2. Direct fy.history() call on a known-live contract (live week)
      3. enumerate_symbols() output sanity
      4. Tiny actual backfill (3 strikes around ATM, history_back_days)
      5. Verify rows landed + corruption guards behaved
    """
    from app.fyers import client as fy
    from app.data import option_history

    result: dict = {"underlying": underlying, "stages": {}}

    # ── 1. Auth ──────────────────────────────────────────────────────
    is_demo = await fy.is_demo()
    token = await fy.get_access_token()
    result["stages"]["1_auth"] = {
        "is_demo": is_demo,
        "has_token": bool(token),
        "token_preview": (token[:12] + "...") if token else None,
        "verdict": "FAIL — not authenticated" if is_demo else "PASS",
    }
    if is_demo:
        result["overall"] = "FAIL at stage 1: log in to Fyers first."
        return result

    # ── 2. Direct Fyers history call on a likely-live contract ───────
    # Build the symbol for the next weekly expiry around current ATM.
    # We call enumerate first just to get a valid in-window contract.
    try:
        symbols, today = await option_history.enumerate_symbols(
            underlying, history_back_days=14,
            forward_weeklies=2, strikes_around_atm=2,
        )
        # Pick the LAST symbol — those are forward expiries (alive)
        test_sym = symbols[-1] if symbols else None
    except Exception as e:
        result["stages"]["2_history_call"] = {
            "verdict": f"FAIL — enumerate_symbols error: {e}",
        }
        result["overall"] = "FAIL at stage 2"
        return result

    if not test_sym:
        result["stages"]["2_history_call"] = {
            "verdict": "FAIL — no symbols enumerated",
        }
        result["overall"] = "FAIL at stage 2"
        return result

    start = (today - timedelta(days=history_back_days)).isoformat()
    end = today.isoformat()
    try:
        h = await fy.history(test_sym, resolution="1",
                             range_from=start, range_to=end)
        candles = h.get("candles") or []
        first = candles[0] if candles else None
        last = candles[-1] if candles else None
        result["stages"]["2_history_call"] = {
            "symbol": test_sym,
            "window": f"{start}..{end}",
            "n_candles": len(candles),
            "first_candle": first,
            "last_candle": last,
            "verdict": "PASS" if len(candles) > 0 else "WARN — 0 candles (may be a dead contract or quiet day)",
        }
    except Exception as e:
        result["stages"]["2_history_call"] = {
            "symbol": test_sym,
            "verdict": f"FAIL — fy.history error: {e}",
        }
        result["overall"] = "FAIL at stage 2"
        return result

    # ── 3. Symbol enumeration sanity ─────────────────────────────────
    result["stages"]["3_enumerate_symbols"] = {
        "total_symbols": len(symbols),
        "first_5": symbols[:5],
        "last_5": symbols[-5:],
        "verdict": "PASS" if len(symbols) > 4 else "FAIL — too few symbols",
    }

    # ── 4. Tiny real backfill ────────────────────────────────────────
    pre_count = (await _count_rows(OptionContract1m, OptionContract1m.underlying == underlying))
    try:
        bf = await option_history.backfill_underlying(
            underlying,
            history_back_days=history_back_days,
            forward_weeklies=2,
            strikes_around_atm=3,
            polite_delay_sec=0.2,
        )
    except Exception as e:
        result["stages"]["4_backfill"] = {"verdict": f"FAIL — {e}"}
        result["overall"] = "FAIL at stage 4"
        return result
    post_count = (await _count_rows(OptionContract1m, OptionContract1m.underlying == underlying))

    result["stages"]["4_backfill"] = {
        "contracts_requested": bf.get("contracts_requested"),
        "candles_inserted": bf.get("candles_inserted"),
        "contracts_dead_before_window": bf.get("contracts_dead_before_window"),
        "contracts_tainted_spot_substitution": bf.get("contracts_tainted_spot_substitution"),
        "contracts_failed": bf.get("contracts_failed"),
        "contracts_empty": bf.get("contracts_empty"),
        "rows_in_db_before": pre_count,
        "rows_in_db_after": post_count,
        "rows_landed_this_run": post_count - pre_count,
        "verdict": "PASS" if (post_count - pre_count) > 0
                   else "WARN — no new rows (may all be dead/tainted/empty)",
    }

    # ── 5. Overall summary ───────────────────────────────────────────
    fails = [k for k, v in result["stages"].items()
             if isinstance(v, dict) and v.get("verdict", "").startswith("FAIL")]
    warns = [k for k, v in result["stages"].items()
             if isinstance(v, dict) and v.get("verdict", "").startswith("WARN")]
    if fails:
        result["overall"] = f"FAIL — {len(fails)} stage(s) failed: {fails}"
    elif warns:
        result["overall"] = f"PASS WITH WARNINGS — {warns}"
    else:
        result["overall"] = "PASS — pipeline healthy"
    return result


async def _count_rows(model, *filters) -> int:
    async with SessionLocal() as s:
        q = select(func.count()).select_from(model)
        for f in filters:
            q = q.where(f)
        return (await s.execute(q)).scalar() or 0


# ── 2. JOB RUNNER ─────────────────────────────────────────────────────
@router.post("/run-job")
async def run_scheduled_job(
    job: str = Query(..., description="One of: daily_options_history, "
                                      "weekly_long_backfill, morning_batch, "
                                      "bhavcopy_daily, dataset_health, "
                                      "fyers_eod_snapshot"),
    _user: dict = Depends(require_superadmin),
):
    """Trigger a scheduled job RIGHT NOW. Useful for verifying a fix
    without waiting for the next cron firing."""
    from app import scheduler as sch
    JOBS = {
        "daily_options_history": sch.daily_options_history_job,
        "weekly_long_backfill": sch.weekly_long_backfill_job,
        "morning_batch": sch.morning_batch_job,
        "bhavcopy_daily": sch.bhavcopy_daily_pull,
        "dataset_health": sch.dataset_health_check,
        "fyers_eod_snapshot": sch.fyers_eod_snapshot,
    }
    fn = JOBS.get(job)
    if not fn:
        raise HTTPException(400, f"Unknown job: {job}. Choose from {list(JOBS.keys())}")
    started = datetime.now(timezone.utc)
    try:
        await fn()
        ok = True
        err = None
    except Exception as e:
        ok = False
        err = str(e)
        log.exception("manual job %s failed", job)
    ended = datetime.now(timezone.utc)
    return {
        "job": job,
        "ok": ok,
        "error": err,
        "duration_sec": round((ended - started).total_seconds(), 1),
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
    }


# ── 3. DAILY FILLS DASHBOARD ──────────────────────────────────────────
@router.get("/daily-fills")
async def daily_fills(
    days: int = Query(14, ge=1, le=90),
    _user: dict = Depends(require_superadmin),
):
    """Per-day row counts per table — powers the dataset-growth dashboard.

    Returns ~14 rows per table, one per day, with the count of rows whose
    timestamp falls on that calendar date.
    """
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)

    async with SessionLocal() as s:
        # Use raw SQL for grouped date aggregation — clean Timescale query.
        out: dict = {"days": days, "from": cutoff.isoformat(), "tables": {}}

        for table, ts_col, extra_dim in [
            ("option_contract_1m", "ts", "underlying"),
            ("option_strike_snapshot", "ts", "underlying"),
            ("tick_1m", "ts", "symbol"),
            ("option_eod", "trade_date", "underlying"),
        ]:
            # Aggregate rows-per-day
            r = await s.execute(text(f"""
                SELECT {ts_col}::date AS day,
                       COUNT(*) AS rows,
                       COUNT(DISTINCT {extra_dim}) AS distinct_keys
                FROM {table}
                WHERE {ts_col} >= :cutoff
                GROUP BY {ts_col}::date
                ORDER BY {ts_col}::date DESC
            """), {"cutoff": cutoff})
            rows = [
                {"day": str(row.day), "rows": int(row.rows),
                 "distinct_keys": int(row.distinct_keys)}
                for row in r
            ]
            total = await s.execute(text(f"SELECT COUNT(*) FROM {table}"))
            out["tables"][table] = {
                "total_rows": total.scalar() or 0,
                "by_day": rows,
                "key_dim": extra_dim,
            }
        return out


# ── 4. RECENT SCHEDULER ACTIVITY (last fired times) ───────────────────
@router.get("/scheduler-status")
async def scheduler_status(_user: dict = Depends(require_superadmin)):
    """List every registered scheduler job and its next firing time."""
    from app.scheduler import scheduler
    if not scheduler.running:
        return {"running": False, "jobs": []}
    jobs = []
    for j in scheduler.get_jobs():
        jobs.append({
            "id": j.id,
            "name": j.name,
            "trigger": str(j.trigger),
            "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
        })
    return {"running": True, "jobs": jobs}
