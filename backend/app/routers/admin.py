"""Admin endpoints — universe management, re-seed, poll status."""
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, Instrument, OptionSnapshot, Tick1m
from app.scheduler import seed_tracked, poll_high, poll_low
from app.store import store
from app.fno_universe import all_high_priority, all_low_priority
from app.routers.user_auth import require_tier

router = APIRouter()


@router.get("/universe")
async def universe(s: AsyncSession = Depends(get_session), user: dict = Depends(require_tier("algo"))):
    """Counts, last poll timestamps, and per-tier breakdown."""
    res = await s.execute(
        select(Instrument.tier, func.count())
        .where(Instrument.tracked == 1)
        .group_by(Instrument.tier)
    )
    counts = {row[0]: row[1] for row in res.fetchall()}

    snap_count = (await s.execute(select(func.count()).select_from(OptionSnapshot))).scalar() or 0
    tick_count = (await s.execute(select(func.count()).select_from(Tick1m))).scalar() or 0
    last_snap = (await s.execute(select(func.max(OptionSnapshot.ts)))).scalar()
    last_tier1 = await store.r.get("poll:last:1")
    last_tier2 = await store.r.get("poll:last:2")

    return {
        "tier_counts": counts,
        "configured_tier1": len(all_high_priority()),
        "configured_tier2": len(all_low_priority()),
        "snapshot_rows": snap_count,
        "tick_rows": tick_count,
        "last_snapshot": last_snap.isoformat() if last_snap else None,
        "last_poll_tier1": last_tier1,
        "last_poll_tier2": last_tier2,
        "server_now": datetime.utcnow().isoformat(),
    }


@router.post("/reseed")
async def reseed(user: dict = Depends(require_tier("algo"))):
    """Re-apply the F&O universe seed list. Idempotent."""
    await seed_tracked()
    return {"ok": True}


@router.post("/poll/{tier}")
async def trigger_poll(tier: int, user: dict = Depends(require_tier("algo"))):
    """Manually trigger a poll loop for a tier (1 or 2). Useful right after
    re-seeding to backfill snapshots without waiting for the next cron."""
    if tier == 1:
        await poll_high()
    elif tier == 2:
        await poll_low()
    else:
        return {"ok": False, "error": "tier must be 1 or 2"}
    return {"ok": True}
