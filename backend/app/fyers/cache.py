"""Cache-then-fetch-then-persist wrapper around Fyers reads.

Two callable entry points:

  get_candles(symbol, resolution, range_from, range_to)
      Read from `tick_1m` first; for any gap days, hit Fyers history
      and UPSERT before returning. Backtest + RL training read through
      this — eliminates per-tune-cell Fyers hammering.

  get_strike_data(underlying, trade_date, expiry, strike, opt_type)
      Routes through the L1→L2→L3→L4 priority chain:
        L1  option_strike_snapshot      (forward intraday, 1-min)
        L2  option_eod                  (NSE Bhavcopy, EOD)
        L3  (paid provider stub)        (returns None for now)
        L4  bs_synthesize_from_spot()   (BS fallback, tagged)
      Returns {"price": float, "source": str, "ts": datetime}.

Every read records its `source` tag so a run's `data_quality.source_mix`
block always knows what's real vs synthesized.
"""
from __future__ import annotations

import logging
from datetime import datetime, date, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal, Tick1m, OptionStrikeSnapshot, OptionEod
from app.fyers import client as fy

log = logging.getLogger("reyu.fyers.cache")


# ── Source tags (for data_quality.source_mix) ───────────────────────
SOURCE_L1_FORWARD = "L1_FORWARD_INTRADAY"
SOURCE_L2_EOD = "L2_BHAVCOPY_EOD"
SOURCE_L3_PAID = "L3_PAID_INTRADAY"
SOURCE_L4_SYNTH = "L4_BS_SYNTHESIZED"


# ── Spot candle cache (Sprint 0.2c) ────────────────────────────────
async def get_candles(
    symbol: str,
    resolution: str,
    range_from: str,
    range_to: str,
) -> dict[str, Any]:
    """Return Fyers-shaped {candles: [[ts, o, h, l, c, v, oi?], …]}.

    Reads from `tick_1m` for the window. For any day that has no rows,
    calls `fy.history()` and UPSERTs before returning. Subsequent reads
    for the same day are cache hits.

    Note: tick_1m stores 1-minute bars; this function returns them as-is.
    Resolution other than "1" / "5" / "15" still hits Fyers (we don't
    resample yet).
    """
    try:
        d_from = datetime.fromisoformat(range_from).date()
        d_to = datetime.fromisoformat(range_to).date()
    except ValueError:
        # Fallback: just hit Fyers, no cache logic
        return await fy.history(symbol, resolution, range_from, range_to)

    # 1. Pull from cache
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(Tick1m).where(
                Tick1m.symbol == symbol,
                Tick1m.ts >= datetime.combine(d_from, datetime.min.time()),
                Tick1m.ts < datetime.combine(d_to + timedelta(days=1), datetime.min.time()),
            ).order_by(Tick1m.ts)
        )).scalars().all()

    cached_days = {r.ts.date() for r in rows}
    expected_days = []
    cur = d_from
    while cur <= d_to:
        if cur.weekday() < 5:                        # only weekdays
            expected_days.append(cur)
        cur += timedelta(days=1)
    missing_days = [d for d in expected_days if d not in cached_days]

    # 2. Fetch missing days from Fyers + persist
    if missing_days:
        log.info("cache miss for %s on %d days, fetching from Fyers",
                 symbol, len(missing_days))
        async with SessionLocal() as s:
            for d in missing_days:
                try:
                    raw = await fy.history(symbol, resolution,
                                           d.isoformat(), d.isoformat())
                except Exception as e:
                    log.warning("history %s %s failed: %s", symbol, d, e)
                    continue
                candles = raw.get("candles") if isinstance(raw, dict) else None
                if not candles:
                    continue
                vals = []
                for c in candles:
                    ts = datetime.utcfromtimestamp(c[0])
                    vals.append({
                        "ts": ts, "symbol": symbol,
                        "open": c[1], "high": c[2], "low": c[3], "close": c[4],
                        "volume": int(c[5] or 0),
                        "oi": int(c[6] or 0) if len(c) > 6 else 0,
                    })
                if vals:
                    await s.execute(
                        pg_insert(Tick1m).values(vals).on_conflict_do_nothing()
                    )
            await s.commit()
        # Re-read for full coverage
        async with SessionLocal() as s:
            rows = (await s.execute(
                select(Tick1m).where(
                    Tick1m.symbol == symbol,
                    Tick1m.ts >= datetime.combine(d_from, datetime.min.time()),
                    Tick1m.ts < datetime.combine(d_to + timedelta(days=1), datetime.min.time()),
                ).order_by(Tick1m.ts)
            )).scalars().all()

    return {
        "candles": [
            [int(r.ts.timestamp()), r.open, r.high, r.low, r.close,
             r.volume, r.oi]
            for r in rows
        ],
        "source": SOURCE_L1_FORWARD if not missing_days else "L1_FORWARD_WITH_FYERS_BACKFILL",
    }


async def get_daily_candles(
    symbol: str,
    range_from: str,
    range_to: str,
) -> dict[str, Any]:
    """Daily OHLCV resampled from `tick_1m` **in SQL** — one row per NSE
    session, not the raw 1-minute stream.

    `get_candles(resolution="D")` materializes every 1-minute row (100k+
    for a liquid stock over a year) into Python and resamples there, which
    took ~2 minutes for a single equity-analysis chat turn. This does the
    OHLCV rollup in Postgres and returns ~250 daily rows, so the equity /
    indicator skills answer in well under a second. Days are grouped on the
    IST calendar date to match `_to_daily`; open/close are the first/last
    bar of each session. No Fyers backfill — reads whatever is cached."""
    try:
        d_from = datetime.fromisoformat(range_from).date()
        d_to = datetime.fromisoformat(range_to).date()
    except ValueError:
        return {"candles": [], "source": SOURCE_L1_FORWARD}

    q = text(
        """
        SELECT
            min(ts)                                  AS ts_min,
            (array_agg("open"  ORDER BY ts ASC))[1]  AS o,
            max(high)                                AS h,
            min(low)                                 AS l,
            (array_agg(close   ORDER BY ts DESC))[1] AS c,
            sum(volume)                              AS v
        FROM tick_1m
        WHERE symbol = :sym AND ts >= :f AND ts < :t
        GROUP BY ((ts AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata')::date)
        ORDER BY min(ts)
        """
    )
    async with SessionLocal() as s:
        res = (await s.execute(q, {
            "sym": symbol,
            "f": datetime.combine(d_from, datetime.min.time()),
            "t": datetime.combine(d_to + timedelta(days=1), datetime.min.time()),
        })).all()

    candles = [
        [int(r.ts_min.timestamp()), float(r.o), float(r.h), float(r.l),
         float(r.c), int(r.v or 0)]
        for r in res
    ]
    return {"candles": candles, "source": SOURCE_L1_FORWARD}


# ── Strike data priority resolver (Sprint 0.2b) ────────────────────
async def get_strike_data(
    underlying: str,
    trade_date: date,
    expiry: datetime,
    strike: float,
    option_type: str,                       # "CE" | "PE"
) -> dict[str, Any] | None:
    """Resolve per-strike data for a (date, expiry, strike, opt_type)
    quadruple. Tries L1 → L2 → L4 (L3 paid stub returns None for now).

    Returns {"close": float, "oi": int, "volume": int, "source": str}
    or None if no source can satisfy.
    """
    # ── L1: forward intraday — last bar of trade_date (close-of-day) ──
    async with SessionLocal() as s:
        row = (await s.execute(
            select(OptionStrikeSnapshot).where(
                OptionStrikeSnapshot.underlying == underlying,
                OptionStrikeSnapshot.expiry == expiry,
                OptionStrikeSnapshot.strike == strike,
                OptionStrikeSnapshot.ts >= datetime.combine(trade_date, datetime.min.time()),
                OptionStrikeSnapshot.ts < datetime.combine(trade_date + timedelta(days=1), datetime.min.time()),
            ).order_by(OptionStrikeSnapshot.ts.desc()).limit(1)
        )).scalar_one_or_none()
        if row:
            return {
                "close":  (row.ce_ltp if option_type == "CE" else row.pe_ltp),
                "oi":     (row.ce_oi if option_type == "CE" else row.pe_oi),
                "volume": (row.ce_volume if option_type == "CE" else row.pe_volume),
                "source": SOURCE_L1_FORWARD,
                "ts":     row.ts,
            }

    # ── L2: NSE Bhavcopy EOD ──────────────────────────────────────
    async with SessionLocal() as s:
        eod = (await s.execute(
            select(OptionEod).where(
                OptionEod.underlying == underlying,
                OptionEod.expiry == expiry,
                OptionEod.strike == strike,
                OptionEod.option_type == option_type,
                OptionEod.trade_date == datetime.combine(trade_date, datetime.min.time()),
            )
        )).scalar_one_or_none()
        if eod:
            return {
                "close": eod.close, "oi": eod.oi, "volume": eod.volume,
                "source": SOURCE_L2_EOD,
                "ts": eod.trade_date,
            }

    # ── L3: paid intraday provider — slot reserved ───────────────
    # if PAID_PROVIDER_AVAILABLE: …

    # ── L4: BS synthesis from spot candle ─────────────────────────
    # Caller can opt-in by passing through `_synth_from_spot()` when None.
    # We deliberately don't auto-synthesize here so backtests can decide
    # whether to fall back or just skip the bar.
    return None


# ── Helper for run quality reporting ────────────────────────────────
def source_mix(rows: list[dict]) -> dict[str, float]:
    """Given a list of `{source: …}` reads, return a percentage breakdown."""
    if not rows:
        return {}
    total = len(rows)
    out: dict[str, int] = {}
    for r in rows:
        s = r.get("source") or "UNKNOWN"
        out[s] = out.get(s, 0) + 1
    return {k: round(v / total * 100, 2) for k, v in out.items()}
