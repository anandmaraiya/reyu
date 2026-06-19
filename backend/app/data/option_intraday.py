"""
NSE F&O Intraday Options Data Ingester — Sprint 0.3.

Three sources:
  1. TradingTuitions  — free NIFTY/BANKNIFTY 1-min options CSV (email-gated Google Drive)
  2. Breeze API       — ICICI Direct, all F&O stocks+indices, 1-second to daily
  3. Google Drive     — bulk CSV imports from community-shared folders

All sources write to `option_intraday` hypertable with a `source` tag
so the data_quality report can show provenance per row.

Usage:
  # TradingTuitions (after manually downloading CSVs)
  POST /api/data/intraday/ingest-csv?path=/path/to/csv&source=tradingtuitions

  # Breeze API (requires ICICI Direct credentials)
  POST /api/data/intraday/breeze/fetch?symbol=NIFTY&date=2024-06-05
  POST /api/data/intraday/breeze/backfill?symbol=NIFTY&start=2024-01-01&end=2024-06-05

  # Google Drive bulk (after downloading folder)
  POST /api/data/intraday/ingest-folder?path=/path/to/folder&source=googledrive
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, OptionIntraday

log = logging.getLogger("reyu.data.intraday")

# ── Column mapping for different CSV formats ──────────────────────────
# TradingTuitions format: Date,Time,Open,High,Low,Close,Volume,OI
# Breeze API format:      date,open,high,low,close,volume,oi (per strike CSV)
# Google Drive format:    Date,Time,Open,High,Low,Close,Volume,OI (same as TT)

TT_COLS = ["Date", "Time", "Open", "High", "Low", "Close", "Volume", "OI"]
BREEZE_COLS = ["date", "open", "high", "low", "close", "volume", "oi"]


def _parse_tt_datetime(date_str: str, time_str: str) -> datetime:
    """Parse TradingTuitions 'DD-MMM-YYYY' + 'HH:MM' format."""
    return datetime.strptime(f"{date_str.strip()} {time_str.strip()}", "%d-%b-%Y %H:%M")


def _parse_breeze_datetime(dt_str: str) -> datetime:
    """Parse Breeze API datetime string."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%b-%Y %H:%M:%S"):
        try:
            return datetime.strptime(dt_str.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {dt_str}")


def _to_fyers_underlying(scrip: str) -> str:
    """Map symbol to canonical reyu underlying."""
    idx_map = {
        "NIFTY": "NSE:NIFTY50-INDEX",
        "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
        "CNXBAN": "NSE:NIFTYBANK-INDEX",
        "NIFFIN": "NSE:FINNIFTY-INDEX",
        "NIFMID": "NSE:MIDCPNIFTY-INDEX",
        "NIFTYNXT50": "NSE:NIFTYNXT50-INDEX",
        "SENSEX": "BSE:SENSEX-INDEX",
        "BANKEX": "BSE:BANKEX-INDEX",
    }
    return idx_map.get(scrip.upper(), f"NSE:{scrip}-EQ")


def _detect_format(headers: list[str]) -> str:
    """Detect CSV format from headers."""
    h = [c.strip().lower() for c in headers]
    if "date" in h and "time" in h:
        return "tradingtuitions"
    if "datetime" in h or ("date" in h and "open" in h and "time" not in h):
        return "breeze"
    if len(h) >= 6 and h[0] in ("date", "datetime") and "open" in h:
        return "generic"
    return "unknown"


def _parse_intraday_csv(
    text: str,
    underlying: str,
    expiry: datetime,
    strike: float,
    opt_type: str,
    source: str = "unknown",
) -> list[dict]:
    """Parse a CSV string into OptionIntraday rows."""
    rows = []
    reader = csv.reader(io.StringIO(text))
    try:
        headers = next(reader)
    except StopIteration:
        return rows

    fmt = _detect_format(headers)
    h = [c.strip().lower() for c in headers]
    idx = {c: i for i, c in enumerate(h)}

    for line in reader:
        if not line or all(c.strip() == "" for c in line):
            continue
        try:
            if fmt == "tradingtuitions":
                ts = _parse_tt_datetime(line[idx["date"]], line[idx["time"]])
                row = {
                    "ts": ts,
                    "underlying": underlying,
                    "expiry": expiry,
                    "strike": strike,
                    "option_type": opt_type,
                    "open": float(line[idx["open"]] or 0),
                    "high": float(line[idx["high"]] or 0),
                    "low": float(line[idx["low"]] or 0),
                    "close": float(line[idx["close"]] or 0),
                    "volume": int(float(line[idx["volume"]] or 0)),
                    "oi": int(float(line[idx.get("oi", -1)] or 0)) if "oi" in idx else 0,
                    "oi_change": 0,
                    "source": source,
                }
            elif fmt in ("breeze", "generic"):
                dt_str = line[idx.get("datetime", idx["date"])]
                ts = _parse_breeze_datetime(dt_str)
                row = {
                    "ts": ts,
                    "underlying": underlying,
                    "expiry": expiry,
                    "strike": strike,
                    "option_type": opt_type,
                    "open": float(line[idx["open"]] or 0),
                    "high": float(line[idx["high"]] or 0),
                    "low": float(line[idx["low"]] or 0),
                    "close": float(line[idx["close"]] or 0),
                    "volume": int(float(line[idx["volume"]] or 0)),
                    "oi": int(float(line[idx.get("oi", -1)] or 0)) if "oi" in idx else 0,
                    "oi_change": 0,
                    "source": source,
                }
            else:
                log.debug("Unknown CSV format, headers: %s", headers)
                continue
            rows.append(row)
        except (ValueError, IndexError, KeyError) as e:
            log.debug("Skip bad row: %s -> %s", line[:5], e)
            continue
    return rows


async def ingest_csv_file(
    file_path: str,
    underlying: str,
    expiry: datetime,
    strike: float,
    opt_type: str,
    source: str = "manual",
) -> dict:
    """Ingest a single CSV file into option_intraday. Returns {rows, file}."""
    p = Path(file_path)
    if not p.exists():
        return {"rows": 0, "file": file_path, "error": "not-found"}

    text = p.read_text(encoding="utf-8")
    rows = await asyncio.to_thread(
        _parse_intraday_csv, text, underlying, expiry, strike, opt_type, source
    )
    if not rows:
        return {"rows": 0, "file": file_path, "error": "empty-or-unparseable"}

    inserted = 0
    BATCH = 2000
    async with SessionLocal() as s:
        for i in range(0, len(rows), BATCH):
            chunk = rows[i : i + BATCH]
            stmt = pg_insert(OptionIntraday).values(chunk).on_conflict_do_update(
                index_elements=[
                    OptionIntraday.ts, OptionIntraday.underlying,
                    OptionIntraday.expiry, OptionIntraday.strike,
                    OptionIntraday.option_type,
                ],
                set_={
                    "open": pg_insert(OptionIntraday).excluded.open,
                    "high": pg_insert(OptionIntraday).excluded.high,
                    "low": pg_insert(OptionIntraday).excluded.low,
                    "close": pg_insert(OptionIntraday).excluded.close,
                    "volume": pg_insert(OptionIntraday).excluded.volume,
                    "oi": pg_insert(OptionIntraday).excluded.oi,
                    "oi_change": pg_insert(OptionIntraday).excluded.oi_change,
                    "source": pg_insert(OptionIntraday).excluded.source,
                },
            )
            await s.execute(stmt)
            inserted += len(chunk)
        await s.commit()

    log.info("Ingested %d rows from %s [%s]", inserted, p.name, source)
    return {"rows": inserted, "file": file_path, "source": source}


async def ingest_folder(
    folder_path: str,
    source: str = "manual",
    symbol_map: Optional[dict] = None,
) -> dict:
    """
    Ingest all CSV files from a folder (recursively).

    Expected file naming (TradingTuitions style):
      NIFTY_25DEC2024_18000_CE.csv
      BANKNIFTY_25DEC2024_47000_PE.csv
      NIFTYWK_01012025_18000_CE.csv  (weekly)

    Or pass a `symbol_map` dict mapping filename patterns to
    (underlying, expiry, strike, opt_type) tuples.
    """
    folder = Path(folder_path)
    if not folder.is_dir():
        return {"rows": 0, "error": f"not a directory: {folder_path}"}

    total = 0
    files_ok = 0
    files_fail = 0
    results = []

    for csv_file in sorted(folder.rglob("*.csv")):
        parsed = _parse_filename(csv_file.name)
        if not parsed:
            log.warning("Cannot parse filename: %s, skipping", csv_file.name)
            files_fail += 1
            continue

        underlying, expiry, strike, opt_type = parsed
        res = await ingest_csv_file(
            str(csv_file), underlying, expiry, strike, opt_type, source
        )
        results.append(res)
        if res.get("rows", 0):
            total += res["rows"]
            files_ok += 1
        else:
            files_fail += 1

    log.info(
        "Folder ingest [%s]: %d rows from %d files (%d failed)",
        folder_path, total, files_ok, files_fail,
    )
    return {
        "rows": total,
        "files_ok": files_ok,
        "files_fail": files_fail,
        "source": source,
        "details": results,
    }


def _parse_filename(fname: str) -> Optional[tuple]:
    """
    Parse TradingTuitions-style filenames.
    Examples:
      NIFTY_25DEC2024_18000_CE.csv
      BANKNIFTY_25DEC2024_47000_PE.csv
      NIFTYWK_01012025_18000_CE.csv
      NIFTY_25DEC2024_18000_CE_weekly.csv
    Returns (underlying, expiry, strike, opt_type) or None.
    """
    import re
    name = fname.replace(".csv", "").strip()

    # Pattern: SYMBOL_EXPIRY_STRIKE_TYPE
    m = re.match(
        r"([A-Z]+WK?)_(\d{2}[A-Z]{3}\d{4})_(\d+(?:\.\d+)?)_(CE|PE)",
        name,
        re.IGNORECASE,
    )
    if not m:
        return None

    raw_sym = m.group(1).upper()
    expiry_str = m.group(2)
    strike = float(m.group(3))
    opt_type = m.group(4).upper()

    # Map symbol
    sym_map = {
        "NIFTY": "NSE:NIFTY50-INDEX",
        "NIFTYWK": "NSE:NIFTY50-INDEX",
        "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
        "BANKNIFTYWK": "NSE:NIFTYBANK-INDEX",
        "FINNIFTY": "NSE:FINNIFTY-INDEX",
        "FINNIFTYWK": "NSE:FINNIFTY-INDEX",
        "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
        "MIDCPNIFTYWK": "NSE:MIDCPNIFTY-INDEX",
    }
    underlying = sym_map.get(raw_sym)
    if not underlying:
        underlying = f"NSE:{raw_sym}-EQ"

    try:
        expiry = datetime.strptime(expiry_str, "%d%b%Y")
    except ValueError:
        log.warning("Cannot parse expiry from: %s", expiry_str)
        return None

    return (underlying, expiry, strike, opt_type)


# ── Breeze API ingester ───────────────────────────────────────────────

async def breeze_fetch_day(
    breeze_client,
    scrip: str,
    expiry: datetime,
    trade_date: date,
    strike_range: tuple[float, float, float] = (0, 99999, 50),
    interval: str = "1minute",
) -> dict:
    """
    Fetch one day of intraday options data via Breeze API.

    Args:
        breeze_client: authenticated BreezeConnect instance
        scrip: 'NIFTY', 'CNXBAN', 'NIFFIN', 'RELIANCE', etc.
        expiry: expiry datetime
        trade_date: date to fetch
        strike_range: (start, end, step) for strikes
        interval: '1second', '1minute', '5minute', etc.

    Returns: {rows, scrip, date, strikes_fetched}
    """
    from BreezeHistoricalOptions import Breezy

    start_dt = datetime.combine(trade_date, datetime.min.time().replace(hour=9, minute=15))
    end_dt = datetime.combine(trade_date, datetime.min.time().replace(hour=15, minute=29))

    start_strike, end_strike, step = strike_range

    # Breezy.fetch_data writes CSVs to disk; we then parse them
    export_path = f"/tmp/breeze_intraday/{scrip}/{trade_date.isoformat()}"
    os.makedirs(export_path, exist_ok=True)

    try:
        Breezy.fetch_data(
            api=breeze_client,
            scrip=scrip,
            exch="NFO",
            expiry_date=expiry,
            start_datetime=start_dt,
            end_datetime=end_dt,
            start_strike=start_strike,
            end_strike=end_strike,
            step=step,
            max_threads=3,
            interval=interval,
            export_path=export_path,
        )
    except Exception as e:
        log.error("Breeze fetch failed for %s %s: %s", scrip, trade_date, e)
        return {"rows": 0, "scrip": scrip, "date": trade_date.isoformat(), "error": str(e)}

    # Parse all generated CSVs
    total_rows = 0
    for csv_file in Path(export_path).rglob("*.csv"):
        # Filename format: {strike}_{opt_type}.csv
        parts = csv_file.stem.split("_")
        if len(parts) != 2:
            continue
        try:
            strike = float(parts[0])
            opt_type = "CE" if parts[1].upper() == "CE" else "PE"
        except ValueError:
            continue

        res = await ingest_csv_file(
            str(csv_file),
            _to_fyers_underlying(scrip),
            expiry,
            strike,
            opt_type,
            source="breeze",
        )
        total_rows += res.get("rows", 0)

    return {
        "rows": total_rows,
        "scrip": scrip,
        "date": trade_date.isoformat(),
        "export_path": export_path,
    }


# ── Status / coverage ─────────────────────────────────────────────────

async def get_intraday_status(s: AsyncSession) -> dict:
    """Coverage summary for option_intraday."""
    total = (await s.execute(
        select(func.count()).select_from(OptionIntraday)
    )).scalar() or 0
    if total == 0:
        return {"rows": 0, "coverage": "empty"}

    earliest = (await s.execute(
        select(func.min(OptionIntraday.ts))
    )).scalar()
    latest = (await s.execute(
        select(func.max(OptionIntraday.ts))
    )).scalar()
    n_underlyings = (await s.execute(
        select(func.count(func.distinct(OptionIntraday.underlying)))
    )).scalar() or 0

    # Source breakdown
    source_rows = (await s.execute(
        select(OptionIntraday.source, func.count())
        .group_by(OptionIntraday.source)
        .order_by(func.count().desc())
    )).all()
    by_source = {src: cnt for src, cnt in source_rows}

    # Per-underlying date range
    underlyings = (await s.execute(
        select(
            OptionIntraday.underlying,
            func.min(OptionIntraday.ts),
            func.max(OptionIntraday.ts),
            func.count(),
        ).group_by(OptionIntraday.underlying)
    )).all()

    return {
        "rows": total,
        "earliest_ts": earliest.isoformat() if earliest else None,
        "latest_ts": latest.isoformat() if latest else None,
        "distinct_underlyings": n_underlyings,
        "by_source": by_source,
        "underlyings": [
            {
                "underlying": u,
                "earliest": e.isoformat() if e else None,
                "latest": l.isoformat() if l else None,
                "rows": c,
            }
            for u, e, l, c in underlyings
        ],
    }
