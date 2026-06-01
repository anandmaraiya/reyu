"""System status — used by the frontend to gate routes and show health dots.

Returns booleans for Fyers auth, Redis, Postgres reachability + scheduler last-run.
"""
from fastapi import APIRouter
from sqlalchemy import text, select, func

from app.fyers import client as fy
from app.store import store
from app.db import SessionLocal, OptionSnapshot, Instrument

router = APIRouter()


@router.get("/status")
async def status():
    fyers = bool(await fy.get_access_token())

    redis_ok = False
    try:
        await store.r.ping(); redis_ok = True
    except Exception:
        pass

    db_ok = False
    last_snap_ts = None
    tracked_count = 0
    try:
        async with SessionLocal() as s:
            await s.execute(text("SELECT 1"))
            db_ok = True
            last_snap_ts = (await s.execute(select(func.max(OptionSnapshot.ts)))).scalar()
            tracked_count = (await s.execute(
                select(func.count()).select_from(Instrument).where(Instrument.tracked == 1)
            )).scalar() or 0
    except Exception:
        pass

    return {
        "fyers": fyers,
        "demo_mode": not fyers,
        "redis": redis_ok,
        "postgres": db_ok,
        "last_snapshot_at": last_snap_ts.isoformat() if last_snap_ts else None,
        "tracked_symbols": tracked_count,
    }
