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

# URL templates — NSE migrated to the UDiFF Bhavcopy ~2024-07-08
_OLD_BASE = "https://archives.nseindia.com/content/historical/DERIVATIVES"
_NEW_BASE = "https://nsearchives.nseindia.com/content/fo"
_UDIFF_CUTOVER = date(2024, 7, 8)

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _url_for(d: date) -> str:
    if d >= _UDIFF_CUTOVER:
        # New UDiFF format: BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip
        return f"{_NEW_BASE}/BhavCopy_NSE_FO_0_0_0_{d.strftime('%Y%m%d')}_F_0000.csv.zip"
    fname = f"fo{d.day:02d}{_MONTHS[d.month - 1]}{d.year}bhav.csv.zip"
    return f"{_OLD_BASE}/{d.year}/{_MONTHS[d.month - 1]}/{fname}"


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
    """Parse the inner CSV. Auto-detects old (pre-Jul-2024) vs new UDiFF
    format from the header and dispatches."""
    out: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        name = next(n for n in zf.namelist() if not n.endswith("/"))
        with zf.open(name) as f:
            text_io = io.TextIOWrapper(f, encoding="utf-8")
            header_line = text_io.readline()
            header = [h.strip() for h in header_line.split(",")]
            idx = {h: i for i, h in enumerate(header)}
            if "INSTRUMENT" in idx and "SYMBOL" in idx and "EXPIRY_DT" in idx:
                return _parse_old_format(text_io, idx)
            if "FinInstrmTp" in idx and "TckrSymb" in idx and "XpryDt" in idx:
                return _parse_udiff_format(text_io, idx)
            log.warning("Bhavcopy header unrecognised: %s", header[:8])
            return out
    return out


def _parse_old_format(text_io, idx: dict[str, int]) -> list[dict]:
    """Original Bhavcopy CSV format used pre-2024-07-08."""
    out: list[dict] = []
    req = ["INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR",
           "OPTION_TYP", "OPEN", "HIGH", "LOW", "CLOSE",
           "SETTLE_PR", "CONTRACTS", "OPEN_INT", "CHG_IN_OI", "TIMESTAMP"]
    if any(c not in idx for c in req):
        log.warning("old bhavcopy missing cols: %s", set(req) - set(idx))
        return out
    for line in text_io:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < len(req):
            continue
        try:
            out.append({
                "instrument": parts[idx["INSTRUMENT"]],
                "symbol":     parts[idx["SYMBOL"]],
                "expiry":     _parse_old_date(parts[idx["EXPIRY_DT"]]),
                "strike":     float(parts[idx["STRIKE_PR"]] or 0),
                "opt_type":   parts[idx["OPTION_TYP"]] or "XX",
                "open":       float(parts[idx["OPEN"]] or 0),
                "high":       float(parts[idx["HIGH"]] or 0),
                "low":        float(parts[idx["LOW"]] or 0),
                "close":      float(parts[idx["CLOSE"]] or 0),
                "settle":     float(parts[idx["SETTLE_PR"]] or 0),
                "volume":     int(parts[idx["CONTRACTS"]] or 0),
                "oi":         int(parts[idx["OPEN_INT"]] or 0),
                "oi_change":  int(parts[idx["CHG_IN_OI"]] or 0),
                "trade_date": _parse_old_date(parts[idx["TIMESTAMP"]]),
            })
        except Exception as e:
            log.debug("skip bad old row: %s -> %s", line[:80], e)
            continue
    return out


def _parse_udiff_format(text_io, idx: dict[str, int]) -> list[dict]:
    """NSE UDiFF Bhavcopy format used 2024-07-08 onwards.

    Maps new column names + instrument codes back to the old shape so
    downstream UPSERT logic doesn't need to change.
    """
    out: list[dict] = []
    req = ["TradDt", "FinInstrmTp", "TckrSymb", "XpryDt", "StrkPric",
           "OptnTp", "OpnPric", "HghPric", "LwPric", "ClsPric",
           "SttlmPric", "TtlTradgVol", "OpnIntrst", "ChngInOpnIntrst"]
    if any(c not in idx for c in req):
        log.warning("udiff missing cols: %s", set(req) - set(idx))
        return out
    # Map UDiFF instrument types to old codes for downstream filtering
    INSTR_MAP = {"IDO": "OPTIDX", "STO": "OPTSTK", "IDF": "FUTIDX", "STF": "FUTSTK"}
    for line in text_io:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < len(idx):
            continue
        try:
            raw_instr = parts[idx["FinInstrmTp"]]
            out.append({
                "instrument": INSTR_MAP.get(raw_instr, raw_instr),
                "symbol":     parts[idx["TckrSymb"]],
                "expiry":     _parse_iso_date(parts[idx["XpryDt"]]),
                "strike":     float(parts[idx["StrkPric"]] or 0),
                "opt_type":   parts[idx["OptnTp"]] or "XX",
                "open":       float(parts[idx["OpnPric"]] or 0),
                "high":       float(parts[idx["HghPric"]] or 0),
                "low":        float(parts[idx["LwPric"]] or 0),
                "close":      float(parts[idx["ClsPric"]] or 0),
                "settle":     float(parts[idx["SttlmPric"]] or 0),
                "volume":     int(parts[idx["TtlTradgVol"]] or 0),
                "oi":         int(parts[idx["OpnIntrst"]] or 0),
                "oi_change":  int(parts[idx["ChngInOpnIntrst"]] or 0),
                "trade_date": _parse_iso_date(parts[idx["TradDt"]]),
            })
        except Exception as e:
            log.debug("skip bad udiff row: %s -> %s", line[:80], e)
            continue
    return out


def _parse_old_date(s: str) -> datetime:
    """Old format: 'DD-MMM-YYYY' (e.g. '06-JUN-2026')."""
    return datetime.strptime(s.strip(), "%d-%b-%Y")


def _parse_iso_date(s: str) -> datetime:
    """UDiFF format: 'YYYY-MM-DD' (e.g. '2024-07-15')."""
    return datetime.strptime(s.strip(), "%Y-%m-%d")


# Backwards-compat alias for any external callers
_parse_nse_date = _parse_old_date


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
