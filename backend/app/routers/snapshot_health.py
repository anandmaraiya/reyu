"""Snapshot-pipeline health monitoring.

During market hours (Mon-Fri 09:15-15:30 IST) the scheduler writes one
`option_snapshot` row per tier-1 underlying every 60 seconds, and ~21
`option_strike_snapshot` rows per underlying. If the laptop sleeps, the
internet drops, or Fyers throttles, those rows are lost — there is no
historical chain endpoint to backfill from, so the gap is permanent.

This module quantifies the gap so we know data quality at a glance:

  GET /api/data/snapshot-health?underlying=NSE:NIFTY50-INDEX&date=2026-06-09

returns:
  {
    expected_minutes: 375,             # 15:30 - 09:15
    observed_minutes: 372,
    coverage_pct: 99.2,
    longest_gap_minutes: 2,
    gaps: [{from, to, minutes}, …]
  }

Use this to (a) confirm Monday's run was clean, (b) decide whether to
retrain on a noisy day or skip it.
"""
from __future__ import annotations

from datetime import datetime, date, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, OptionSnapshot, OptionStrikeSnapshot

router = APIRouter()

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN_MIN = 9 * 60 + 15           # 09:15 IST
MARKET_CLOSE_MIN = 15 * 60 + 30         # 15:30 IST


def _ist_date_bounds(d: date) -> tuple[datetime, datetime]:
    """Trading window for date `d` in IST, returned as UTC-naive
    timestamps (which is what the DB stores)."""
    open_ist = datetime(d.year, d.month, d.day, 9, 15, tzinfo=IST)
    close_ist = datetime(d.year, d.month, d.day, 15, 30, tzinfo=IST)
    return (
        open_ist.astimezone(timezone.utc).replace(tzinfo=None),
        close_ist.astimezone(timezone.utc).replace(tzinfo=None),
    )


@router.get("/snapshot-health")
async def snapshot_health(
    underlying: str = Query(...),
    target_date: date | None = Query(None, alias="date",
        description="ISO date; defaults to today"),
    s: AsyncSession = Depends(get_session),
):
    """Coverage report for one (underlying, date)."""
    d = target_date or datetime.utcnow().date()
    open_utc, close_utc = _ist_date_bounds(d)

    # Expected = number of 1-min boundaries inside the trading window
    expected_minutes = int((close_utc - open_utc).total_seconds() // 60) + 1

    # Pull all observed timestamps for this underlying on that day
    rows = (await s.execute(
        select(OptionSnapshot.ts)
        .where(OptionSnapshot.symbol == underlying,
               OptionSnapshot.ts >= open_utc,
               OptionSnapshot.ts <= close_utc)
        .order_by(OptionSnapshot.ts)
    )).all()
    observed = [r[0].replace(second=0, microsecond=0) for r in rows]
    observed_set = set(observed)

    # Walk minute-by-minute, identify gaps
    gaps = []
    gap_start = None
    cursor = open_utc.replace(second=0, microsecond=0)
    while cursor <= close_utc:
        if cursor in observed_set:
            if gap_start is not None:
                gaps.append({
                    "from": gap_start.isoformat(),
                    "to": cursor.isoformat(),
                    "minutes": int((cursor - gap_start).total_seconds() // 60),
                })
                gap_start = None
        else:
            if gap_start is None:
                gap_start = cursor
        cursor += timedelta(minutes=1)
    if gap_start is not None and gap_start < close_utc:
        gaps.append({
            "from": gap_start.isoformat(),
            "to": close_utc.isoformat(),
            "minutes": int((close_utc - gap_start).total_seconds() // 60),
        })

    longest_gap = max((g["minutes"] for g in gaps), default=0)
    observed_minutes = len(observed_set)
    coverage = round(observed_minutes / expected_minutes * 100, 2) if expected_minutes else 0

    # Strike snapshot row count for the same window — sanity check the
    # per-strike pipeline kept up too.
    strike_count = (await s.execute(
        select(func.count()).select_from(OptionStrikeSnapshot)
        .where(OptionStrikeSnapshot.underlying == underlying,
               OptionStrikeSnapshot.ts >= open_utc,
               OptionStrikeSnapshot.ts <= close_utc)
    )).scalar() or 0

    return {
        "underlying": underlying,
        "date": d.isoformat(),
        "expected_minutes": expected_minutes,
        "observed_minutes": observed_minutes,
        "coverage_pct": coverage,
        "longest_gap_minutes": longest_gap,
        "strike_snapshot_rows": strike_count,
        "expected_strike_rows_per_minute": 21,     # ATM±10
        "gap_count": len(gaps),
        "gaps": gaps[:20],                          # cap for response size
    }


@router.get("/snapshot-health/today")
async def snapshot_health_today(
    s: AsyncSession = Depends(get_session),
):
    """All tier-1 underlyings, today. Quick dashboard call."""
    from app.fno_universe import all_high_priority

    d = datetime.utcnow().date()
    out = []
    for sym in all_high_priority():
        try:
            row = await snapshot_health(underlying=sym, target_date=d, s=s)
            out.append({
                "underlying": sym,
                "coverage_pct": row["coverage_pct"],
                "observed": row["observed_minutes"],
                "expected": row["expected_minutes"],
                "longest_gap": row["longest_gap_minutes"],
                "strike_rows": row["strike_snapshot_rows"],
            })
        except Exception as e:
            out.append({"underlying": sym, "error": str(e)})
    out.sort(key=lambda r: r.get("coverage_pct", 0))   # worst first
    return {"date": d.isoformat(), "symbols": out}
