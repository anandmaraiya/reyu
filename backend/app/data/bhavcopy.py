"""NSE F&O Bhavcopy ingester — Sprint 0.2a.

Source: https://archives.nseindia.com/content/historical/DERIVATIVES/{YYYY}/{MMM}/fo{DDMMMYYYY}bhav.csv.zip

NSE publishes one ZIP per trading day. Inside is a CSV with columns:
  INSTRUMENT, SYMBOL, EXPIRY_DT, STRIKE_PR, OPTION_TYP, OPEN, HIGH, LOW,
  CLOSE, SETTLE_PR, CONTRACTS, VAL_INLAKH, OPEN_INT, CHG_IN_OI, TIMESTAMP

Coverage: from 2011 (NIFTY weeklies later, BANKNIFTY weeklies from 2016).

This module:
  * `fetch_one(date)` pulls + parses + upserts a single day
  * `backfill(start, end)` loops calendar with rate-limit-friendly pauses
  * scheduler job at 18:00 IST pulls *today's* file on every weekday

Honest about gaps: NSE skips weekends + holidays; we just retry the
next day. Missing files are logged but do not raise.
"""
from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from datetime import date, datetime, timedelta
from typing import Iterable

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal, OptionEod

log = logging.getLogger("reyu.data.bhavcopy")

# URL template
_BASE = "https://archives.nseindia.com/content/historical/DERIVATIVES"

# NSE expects "01JAN2026" style upper-case
_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _url_for(d: date) -> str:
    fname = f"fo{d.day:02d}{_MONTHS[d.month - 1]}{d.year}bhav.csv.zip"
    return f"{_BASE}/{d.year}/{_MONTHS[d.month - 1]}/{fname}"


async def _download(d: date) -> bytes | None:
    url = _url_for(d)
    headers = {
        # NSE blocks empty/curl UAs. Plain browser UA works.
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Reyu/1.0",
        "Accept": "*/*",
        "Referer": "https://www.nseindia.com/",
    }
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            r = await c.get(url, headers=headers)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
    except Exception as e:
        log.warning("Bhavcopy download %s failed: %s", d, e)
        return None


def _parse_csv_bytes(zip_bytes: bytes) -> list[dict]:
    """Parse the inner CSV. Returns one dict per row."""
    out: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # Single CSV inside — first non-dir entry
        name = next(n for n in zf.namelist() if not n.endswith("/"))
        with zf.open(name) as f:
            text_io = io.TextIOWrapper(f, encoding="utf-8")
            header = [h.strip() for h in text_io.readline().split(",")]
            idx = {h: i for i, h in enumerate(header)}
            req = ["INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR",
                   "OPTION_TYP", "OPEN", "HIGH", "LOW", "CLOSE",
                   "SETTLE_PR", "CONTRACTS", "OPEN_INT", "CHG_IN_OI", "TIMESTAMP"]
            if any(c not in idx for c in req):
                log.warning("Bhavcopy header missing expected cols: %s", header)
                return out
            for line in text_io:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < len(req):
                    continue
                try:
                    out.append({
                        "instrument": parts[idx["INSTRUMENT"]],   # OPTIDX, OPTSTK, FUTIDX…
                        "symbol":     parts[idx["SYMBOL"]],
                        "expiry":     _parse_nse_date(parts[idx["EXPIRY_DT"]]),
                        "strike":     float(parts[idx["STRIKE_PR"]] or 0),
                        "opt_type":   parts[idx["OPTION_TYP"]] or "XX",   # CE/PE/XX
                        "open":       float(parts[idx["OPEN"]] or 0),
                        "high":       float(parts[idx["HIGH"]] or 0),
                        "low":        float(parts[idx["LOW"]] or 0),
                        "close":      float(parts[idx["CLOSE"]] or 0),
                        "settle":     float(parts[idx["SETTLE_PR"]] or 0),
                        "volume":     int(parts[idx["CONTRACTS"]] or 0),
                        "oi":         int(parts[idx["OPEN_INT"]] or 0),
                        "oi_change":  int(parts[idx["CHG_IN_OI"]] or 0),
                        "trade_date": _parse_nse_date(parts[idx["TIMESTAMP"]]),
                    })
                except Exception as e:
                    log.debug("skip bad row: %s -> %s", line[:80], e)
                    continue
    return out


def _parse_nse_date(s: str) -> datetime:
    """NSE formats: 'DD-MMM-YYYY' (e.g. '06-JUN-2026')."""
    return datetime.strptime(s.strip(), "%d-%b-%Y")


def _to_fyers_underlying(scrip: str, instrument: str) -> str:
    """Map Bhavcopy `SYMBOL` to the canonical reyu spot symbol."""
    if instrument in ("OPTIDX", "FUTIDX"):
        idx_map = {
            "NIFTY":      "NSE:NIFTY50-INDEX",
            "BANKNIFTY":  "NSE:NIFTYBANK-INDEX",
            "FINNIFTY":   "NSE:FINNIFTY-INDEX",
            "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
            "NIFTYNXT50": "NSE:NIFTYNXT50-INDEX",
        }
        return idx_map.get(scrip, f"NSE:{scrip}-INDEX")
    return f"NSE:{scrip}-EQ"


async def fetch_one(d: date) -> dict:
    """Pull + upsert one trading day. Returns {date, rows, skipped}."""
    if d.weekday() >= 5:
        return {"date": d.isoformat(), "rows": 0, "skipped": "weekend"}
    raw = await _download(d)
    if not raw:
        return {"date": d.isoformat(), "rows": 0, "skipped": "no-file"}

    # CSV parse is CPU-bound on 40k+ rows — offload so the asyncio
    # event loop keeps serving live HTTP traffic during backfill.
    parsed = await asyncio.to_thread(_parse_csv_bytes, raw)
    if not parsed:
        return {"date": d.isoformat(), "rows": 0, "skipped": "empty-csv"}

    # Map to OptionEod rows (skip futures — they go to a future table later)
    values: list[dict] = []
    for r in parsed:
        if r["opt_type"] not in ("CE", "PE"):
            continue                                     # skip FUT rows for now
        values.append({
            "trade_date": r["trade_date"],
            "underlying": _to_fyers_underlying(r["symbol"], r["instrument"]),
            "expiry":     r["expiry"],
            "strike":     r["strike"],
            "option_type": r["opt_type"],
            "open": r["open"], "high": r["high"], "low": r["low"],
            "close": r["close"], "settle": r["settle"],
            "volume": r["volume"], "oi": r["oi"], "oi_change": r["oi_change"],
        })

    inserted = 0
    BATCH = 2000
    async with SessionLocal() as s:
        for i in range(0, len(values), BATCH):
            chunk = values[i:i + BATCH]
            stmt = pg_insert(OptionEod).values(chunk).on_conflict_do_update(
                index_elements=[
                    OptionEod.trade_date, OptionEod.underlying,
                    OptionEod.expiry, OptionEod.strike, OptionEod.option_type,
                ],
                set_={
                    "open": pg_insert(OptionEod).excluded.open,
                    "high": pg_insert(OptionEod).excluded.high,
                    "low":  pg_insert(OptionEod).excluded.low,
                    "close": pg_insert(OptionEod).excluded.close,
                    "settle": pg_insert(OptionEod).excluded.settle,
                    "volume": pg_insert(OptionEod).excluded.volume,
                    "oi": pg_insert(OptionEod).excluded.oi,
                    "oi_change": pg_insert(OptionEod).excluded.oi_change,
                },
            )
            await s.execute(stmt)
            inserted += len(chunk)
        await s.commit()
    log.info("Bhavcopy %s: %d option rows ingested", d, inserted)
    return {"date": d.isoformat(), "rows": inserted}


async def backfill(start: date, end: date,
                   pause_seconds: float = 1.5) -> dict:
    """Loop calendar [start, end] inclusive, polite to NSE."""
    import asyncio
    total = 0; days = 0; skipped = 0
    cur = start
    while cur <= end:
        res = await fetch_one(cur)
        if res.get("rows", 0):
            total += res["rows"]; days += 1
        elif res.get("skipped") in ("no-file", "empty-csv"):
            skipped += 1
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            await asyncio.sleep(pause_seconds)
    return {"start": start.isoformat(), "end": end.isoformat(),
            "days_ingested": days, "days_skipped": skipped,
            "rows_total": total}


# ── Scheduler hook ──────────────────────────────────────────────────
async def daily_pull_today() -> None:
    """Called by APScheduler at 18:00 IST every weekday. Pulls *today's*
    file (NSE publishes Bhavcopy ~17:30 IST)."""
    today = datetime.utcnow().date() + timedelta(hours=5, minutes=30)
    today = today.date() if hasattr(today, "date") else today
    today = date.today()                         # simpler — server in container UTC
    try:
        res = await fetch_one(today)
        log.info("daily Bhavcopy pull: %s", res)
    except Exception as e:
        log.exception("daily Bhavcopy pull failed: %s", e)
