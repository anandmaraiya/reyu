"""
Intraday data admin endpoints — Sprint 0.3.

POST /api/data/intraday/ingest-csv     — ingest a single CSV file
POST /api/data/intraday/ingest-folder  — ingest all CSVs from a folder
POST /api/data/intraday/breeze/fetch    — fetch one day via Breeze API
POST /api/data/intraday/breeze/backfill — multi-day Breeze backfill (background)
GET  /api/data/intraday/status          — coverage report
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, OptionIntraday
from app.data.option_intraday import (
    ingest_csv_file,
    ingest_folder,
    breeze_fetch_day,
    get_intraday_status,
)

router = APIRouter()
log = logging.getLogger("reyu.routers.intraday")


@router.post("/intraday/ingest-csv")
async def intraday_ingest_csv(
    file_path: str = Query(..., description="Absolute path to CSV file"),
    underlying: str = Query(..., description="Underlying symbol, e.g. NSE:NIFTY50-INDEX"),
    expiry: str = Query(..., description="Expiry date, e.g. 2024-12-25"),
    strike: float = Query(..., description="Strike price"),
    option_type: str = Query(..., regex="^(CE|PE)$"),
    source: str = Query("manual", description="Data source tag"),
):
    """Ingest a single CSV file into option_intraday."""
    try:
        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "expiry must be YYYY-MM-DD")

    res = await ingest_csv_file(file_path, underlying, expiry_dt, strike, option_type, source)
    if res.get("error"):
        raise HTTPException(400, res["error"])
    return res


@router.post("/intraday/ingest-folder")
async def intraday_ingest_folder(
    folder_path: str = Query(..., description="Absolute path to folder containing CSV files"),
    source: str = Query("tradingtuitions", description="Data source tag"),
):
    """
    Ingest all CSV files from a folder (recursively).
    Filenames must match pattern: SYMBOL_EXPIRY_STRIKE_TYPE.csv
    e.g. NIFTY_25DEC2024_18000_CE.csv
    """
    res = await ingest_folder(folder_path, source=source)
    if res.get("error"):
        raise HTTPException(400, res["error"])
    return res


@router.post("/intraday/breeze/fetch")
async def intraday_breeze_fetch(
    scrip: str = Query(..., description="Breeze scrip code: NIFTY, CNXBAN, NIFFIN, etc."),
    expiry: str = Query(..., description="Expiry date YYYY-MM-DD"),
    trade_date: str = Query(..., description="Trade date YYYY-MM-DD"),
    start_strike: float = Query(0),
    end_strike: float = Query(99999),
    step: float = Query(50),
    interval: str = Query("1minute", regex="^(1second|1minute|5minute|15minute|30minute|1hour)$"),
):
    """
    Fetch one day of intraday options data via Breeze API.
    Requires breeze_connect and breeze-historical-options packages installed
    and BREEZE_API_KEY / BREEZE_API_SECRET / BREEZE_SESSION_TOKEN in env.
    """
    try:
        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d")
        trade_dt = date.fromisoformat(trade_date)
    except ValueError as e:
        raise HTTPException(400, f"Invalid date: {e}")

    # Lazy import so the app works without breeze packages installed
    try:
        from breeze_connect import BreezeConnect
        from BreezeHistoricalOptions import autologin
    except ImportError:
        raise HTTPException(
            501,
            "breeze_connect and breeze-historical-options not installed. "
            "Run: pip install breeze-connect breeze-historical-options",
        )

    import yaml, os
    cred_path = os.path.join(os.path.dirname(__file__), "..", "..", "cred.yml")
    if not os.path.exists(cred_path):
        raise HTTPException(501, f"cred.yml not found at {cred_path}")

    with open(cred_path) as f:
        cred = yaml.load(f, Loader=yaml.FullLoader)

    breeze = BreezeConnect(api_key=cred["api_key"])
    try:
        session_key = autologin.get_session_key(cred=cred, force=False)
    except Exception:
        session_key = autologin.get_session_key(cred=cred, force=True)
    breeze.generate_session(api_secret=cred["api_secret"], session_token=session_key)

    res = await breeze_fetch_day(
        breeze, scrip, expiry_dt, trade_dt,
        strike_range=(start_strike, end_strike, step),
        interval=interval,
    )
    return res


@router.post("/intraday/breeze/backfill")
async def intraday_breeze_backfill(
    scrip: str = Query(...),
    expiry: str = Query(...),
    start: date = Query(...),
    end: date = Query(...),
    background: BackgroundTasks = None,
):
    """Multi-day Breeze backfill. Runs in background."""
    from datetime import datetime as dt
    expiry_dt = dt.strptime(expiry, "%Y-%m-%d")

    async def _runner():
        from breeze_connect import BreezeConnect
        from BreezeHistoricalOptions import autologin
        import yaml, os
        cred_path = os.path.join(os.path.dirname(__file__), "..", "..", "cred.yml")
        with open(cred_path) as f:
            cred = yaml.load(f, Loader=yaml.FullLoader)
        breeze = BreezeConnect(api_key=cred["api_key"])
        try:
            session_key = autologin.get_session_key(cred=cred, force=False)
        except Exception:
            session_key = autologin.get_session_key(cred=cred, force=True)
        breeze.generate_session(api_secret=cred["api_secret"], session_token=session_key)

        total = 0
        cur = start
        while cur <= end:
            if cur.weekday() < 5:
                res = await breeze_fetch_day(breeze, scrip, expiry_dt, cur)
                total += res.get("rows", 0)
                log.info("Breeze backfill %s %s: %d rows", scrip, cur, res.get("rows", 0))
                await asyncio.sleep(2)  # Rate limit
            cur += timedelta(days=1)
        log.info("Breeze backfill done: %s %s-%s, %d total rows", scrip, start, end, total)

    if background:
        background.add_task(_runner)
        return {"ok": True, "queued": {"scrip": scrip, "start": str(start), "end": str(end)}}
    else:
        await _runner()
        return {"ok": True, "scrip": scrip, "start": str(start), "end": str(end)}


@router.get("/intraday/status")
async def intraday_status(s: AsyncSession = Depends(get_session)):
    """Coverage summary for option_intraday."""
    return await get_intraday_status(s)
