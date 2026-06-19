"""Daily morning batch — 08:00 IST.

Runs **before market open** so the catch-up data is ready for the trading
day. Pulls in priority order:

  1. NSE F&O Bhavcopy for yesterday (in case 18:00 IST cron missed it)
  2. 1-min option-contract history for tracked underlyings (Fyers)
  3. Spot 1-min history catch-up (tick_1m)

Logged + idempotent — re-runs are safe.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from app.data import bhavcopy, option_history
from app.fyers import client as fy
from app.fyers.cache import get_candles

log = logging.getLogger("reyu.morning_batch")

IST = timezone(timedelta(hours=5, minutes=30))

# Tracked underlyings to pull intraday option history for. Keep small
# during morning batch — 1 underlying × 100 days ≈ 6 min of Fyers calls.
MORNING_UNDERLYINGS = [
    "NSE:NIFTY50-INDEX",
    "NSE:NIFTYBANK-INDEX",
    "NSE:FINNIFTY-INDEX",
]

SPOT_HISTORY_SYMBOLS = MORNING_UNDERLYINGS + [
    "NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ", "NSE:TCS-EQ",
]


async def run_morning_batch() -> dict:
    """Top-level entrypoint. Returns a per-task summary."""
    out: dict = {"started_at": datetime.utcnow().isoformat()}

    # ── 1. Yesterday's Bhavcopy ──────────────────────────────────
    now_ist = datetime.now(IST).date()
    yday = now_ist - timedelta(days=1)
    while yday.weekday() >= 5:                # rewind across weekend
        yday -= timedelta(days=1)
    try:
        bres = await bhavcopy.fetch_one(yday)
        out["bhavcopy"] = bres
    except Exception as e:
        out["bhavcopy"] = {"error": str(e)}

    # Stop here if Fyers isn't authed
    if await fy.is_demo():
        out["fyers_history"] = {"skipped": "demo-mode"}
        out["spot_history"] = {"skipped": "demo-mode"}
        log.info("morning batch (limited, demo mode): %s", out)
        return out

    # ── 2. Per-contract 1-min option history (last 30 days) ──────
    fy_hist: dict = {}
    for u in MORNING_UNDERLYINGS:
        try:
            r = await option_history.backfill_underlying(
                u, history_back_days=30,
                forward_weeklies=2, strikes_around_atm=10,
                polite_delay_sec=0.5,
            )
            fy_hist[u] = {
                "candles_inserted": r.get("candles_inserted"),
                "contracts_failed": r.get("contracts_failed"),
            }
        except Exception as e:
            fy_hist[u] = {"error": str(e)}
            log.exception("option_history %s failed", u)
    out["fyers_option_history"] = fy_hist

    # ── 3. Spot 1-min history (last 30 days, cache layer dedups) ─
    today = datetime.utcnow().date()
    start = (today - timedelta(days=30)).isoformat()
    end = today.isoformat()
    spot: dict = {}
    for sym in SPOT_HISTORY_SYMBOLS:
        try:
            r = await get_candles(sym, "1", start, end)
            spot[sym] = len(r.get("candles", []))
        except Exception as e:
            spot[sym] = f"error: {e}"
    out["spot_history"] = spot

    out["ended_at"] = datetime.utcnow().isoformat()
    log.info("morning batch done: %s", out)
    return out
