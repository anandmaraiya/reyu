"""Intraday iron-condor replay with MTM stop — using `option_strike_snapshot`.

The Bhavcopy backtest treats entry/exit as day-open/day-close prices, which
ignores the single most important control on a short-vol strategy: closing
the position when it bleeds intraday. This module replays each day's 1-min
ATM-band snapshots, computes net MTM each minute, and applies a stop.

Inputs per day:
    entry_minute_ist        — e.g. 09:30 IST (skip 15min of open vol)
    eod_close_minute_ist    — e.g. 15:20 IST (hard square-off before 15:30)
    short_strike_offset     — e.g. 50  (OTM1)
    long_strike_offset      — e.g. 400 (OTM8)
    stop_credit_multiple    — e.g. 1.0 → close when MTM < -1×entry_credit

Output per day:
    status: ENTERED / NO_DATA / NO_CREDIT
    if ENTERED:
        entry_credit, exit_debit, pnl, exit_reason in {STOP, EOD}

Returns aggregate metrics + per-trade ledger so the caller can compare
"with stop" vs "without stop" runs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, OptionStrikeSnapshot
from app.sim.engine import compute_roi

log = logging.getLogger("reyu.sim.iron_condor_intraday")

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class IcTrade:
    date: str
    expiry: str | None
    atm_strike: float | None
    entry_ts: str | None
    entry_credit: float | None
    exit_ts: str | None
    exit_debit: float | None
    pnl: float | None
    pnl_pct: float | None
    exit_reason: str          # ENTERED_OK / STOP / EOD / NO_DATA / NO_CREDIT
    max_mtm: float | None = None
    min_mtm: float | None = None


def _ist_to_utc(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=IST).astimezone(timezone.utc).replace(tzinfo=None)


async def _load_day(
    s: AsyncSession, underlying: str, d: date,
) -> dict:
    """Return {ts: {strike: {expiry: {CE: ltp, PE: ltp}}}}."""
    start = _ist_to_utc(d, time(9, 0))
    end = _ist_to_utc(d, time(15, 35))
    rows = (await s.execute(
        select(OptionStrikeSnapshot).where(
            OptionStrikeSnapshot.underlying == underlying,
            OptionStrikeSnapshot.ts >= start,
            OptionStrikeSnapshot.ts <= end,
        )
    )).scalars().all()
    out: dict = {}
    for r in rows:
        out.setdefault(r.ts, {}).setdefault(r.strike, {})[r.expiry] = {
            "CE": r.ce_ltp, "PE": r.pe_ltp,
        }
    return out


def _pick_expiry(by_strike_at_ts: dict, ref_date: date) -> datetime | None:
    """Nearest expiry >= ref_date with any liquid strikes."""
    expiries: set[datetime] = set()
    for strike_map in by_strike_at_ts.values():
        for ex in strike_map.keys():
            expiries.add(ex)
    candidates = [ex for ex in expiries if ex.date() >= ref_date]
    return min(candidates) if candidates else None


def _pick_atm(by_strike_at_ts: dict, expiry: datetime) -> float | None:
    """ATM = strike where |CE - PE| is minimal."""
    best, best_diff = None, float("inf")
    for k, strike_map in by_strike_at_ts.items():
        leg = strike_map.get(expiry)
        if not leg:
            continue
        ce, pe = leg.get("CE"), leg.get("PE")
        if ce and pe and ce > 0 and pe > 0:
            diff = abs(ce - pe)
            if diff < best_diff:
                best_diff, best = diff, k
    return best


def _net_debit(by_strike_at_ts: dict, expiry: datetime, atm: float,
               sho: int, lwo: int) -> float | None:
    """Cost to flatten the condor at this snapshot. None if any leg missing."""
    try:
        sc = by_strike_at_ts[atm + sho][expiry]["CE"]
        sp = by_strike_at_ts[atm - sho][expiry]["PE"]
        lc = by_strike_at_ts[atm + lwo][expiry]["CE"]
        lp = by_strike_at_ts[atm - lwo][expiry]["PE"]
    except KeyError:
        return None
    if not all(p is not None and p > 0 for p in (sc, sp, lc, lp)):
        return None
    return float(sc + sp - lc - lp)


async def replay_day(
    underlying: str,
    d: date,
    *,
    entry_time_ist: time = time(9, 30),
    eod_close_time_ist: time = time(15, 20),
    short_strike_offset: int = 50,
    long_strike_offset: int = 400,
    stop_credit_multiple: float | None = 1.0,
) -> IcTrade:
    async with SessionLocal() as s:
        day_data = await _load_day(s, underlying, d)
    if not day_data:
        return IcTrade(date=d.isoformat(), expiry=None, atm_strike=None,
                       entry_ts=None, entry_credit=None, exit_ts=None,
                       exit_debit=None, pnl=None, pnl_pct=None,
                       exit_reason="NO_DATA")

    minutes = sorted(day_data.keys())
    entry_cutoff = _ist_to_utc(d, entry_time_ist)
    eod_cutoff = _ist_to_utc(d, eod_close_time_ist)
    # First snapshot at-or-after entry cutoff
    entry_ts = next((m for m in minutes if m >= entry_cutoff), None)
    if entry_ts is None:
        return IcTrade(date=d.isoformat(), expiry=None, atm_strike=None,
                       entry_ts=None, entry_credit=None, exit_ts=None,
                       exit_debit=None, pnl=None, pnl_pct=None,
                       exit_reason="NO_DATA")

    expiry = _pick_expiry(day_data[entry_ts], d)
    if expiry is None:
        return IcTrade(date=d.isoformat(), expiry=None, atm_strike=None,
                       entry_ts=entry_ts.isoformat(), entry_credit=None,
                       exit_ts=None, exit_debit=None, pnl=None, pnl_pct=None,
                       exit_reason="NO_DATA")

    atm = _pick_atm(day_data[entry_ts], expiry)
    if atm is None:
        return IcTrade(date=d.isoformat(), expiry=expiry.date().isoformat(),
                       atm_strike=None, entry_ts=entry_ts.isoformat(),
                       entry_credit=None, exit_ts=None, exit_debit=None,
                       pnl=None, pnl_pct=None, exit_reason="NO_DATA")

    entry_debit_to_close = _net_debit(
        day_data[entry_ts], expiry, atm, short_strike_offset, long_strike_offset,
    )
    if entry_debit_to_close is None:
        return IcTrade(date=d.isoformat(), expiry=expiry.date().isoformat(),
                       atm_strike=atm, entry_ts=entry_ts.isoformat(),
                       entry_credit=None, exit_ts=None, exit_debit=None,
                       pnl=None, pnl_pct=None, exit_reason="NO_DATA")
    # entry_credit = the debit we'd have to pay to flatten IS the credit
    # we received when opening (we shorted near, longed far). Sign convention:
    # entry_credit > 0 means we got paid at entry.
    entry_credit = entry_debit_to_close
    if entry_credit <= 0:
        return IcTrade(date=d.isoformat(), expiry=expiry.date().isoformat(),
                       atm_strike=atm, entry_ts=entry_ts.isoformat(),
                       entry_credit=entry_credit, exit_ts=None, exit_debit=None,
                       pnl=None, pnl_pct=None, exit_reason="NO_CREDIT")

    stop_threshold = -stop_credit_multiple * entry_credit if stop_credit_multiple else None

    max_mtm, min_mtm = 0.0, 0.0
    exit_ts, exit_debit, exit_reason = None, None, "DATA_GAP"
    last_valid_debit, last_valid_ts = None, None
    for m in minutes:
        if m <= entry_ts:
            continue
        debit_now = _net_debit(
            day_data[m], expiry, atm, short_strike_offset, long_strike_offset,
        )
        if debit_now is not None:
            last_valid_debit, last_valid_ts = debit_now, m
            mtm = entry_credit - debit_now
            if mtm > max_mtm:
                max_mtm = mtm
            if mtm < min_mtm:
                min_mtm = mtm
            if stop_threshold is not None and mtm < stop_threshold:
                exit_ts, exit_debit, exit_reason = m, debit_now, "STOP"
                break
        if m >= eod_cutoff:
            if last_valid_debit is not None:
                exit_ts, exit_debit, exit_reason = last_valid_ts, last_valid_debit, "EOD"
            # else: DATA_GAP — entered but no minute-by-minute closeout data
            break
    # If we walked off the end of `minutes` without hitting eod_cutoff, use
    # whatever last_valid we had (data ended before 15:20 IST).
    if exit_reason == "DATA_GAP" and last_valid_debit is not None:
        exit_ts, exit_debit, exit_reason = last_valid_ts, last_valid_debit, "EOD_DATA_TRUNC"

    if exit_debit is None:
        return IcTrade(date=d.isoformat(), expiry=expiry.date().isoformat(),
                       atm_strike=atm, entry_ts=entry_ts.isoformat(),
                       entry_credit=round(entry_credit, 2), exit_ts=None,
                       exit_debit=None, pnl=None, pnl_pct=None,
                       exit_reason="DATA_GAP",
                       max_mtm=round(max_mtm, 2), min_mtm=round(min_mtm, 2))

    pnl = entry_credit - exit_debit
    pnl_pct = (pnl / entry_credit) * 100 if entry_credit > 0 else 0
    return IcTrade(
        date=d.isoformat(),
        expiry=expiry.date().isoformat(),
        atm_strike=atm,
        entry_ts=entry_ts.isoformat(),
        entry_credit=round(entry_credit, 2),
        exit_ts=exit_ts.isoformat(),
        exit_debit=round(exit_debit, 2),
        pnl=round(pnl, 2),
        pnl_pct=round(pnl_pct, 2),
        exit_reason=exit_reason,
        max_mtm=round(max_mtm, 2),
        min_mtm=round(min_mtm, 2),
    )


async def replay_window(
    underlying: str,
    start_date: date, end_date: date,
    *,
    entry_time_ist: time = time(9, 30),
    eod_close_time_ist: time = time(15, 20),
    short_strike_offset: int = 50,
    long_strike_offset: int = 400,
    stop_credit_multiple: float | None = 1.0,
    starting_capital: float = 100_000,
    lot_size: int = 65,
) -> dict:
    """Replay every trading day in [start, end] and aggregate."""
    cur = start_date
    trades: list[IcTrade] = []
    while cur <= end_date:
        if cur.weekday() < 5:               # Mon-Fri
            t = await replay_day(
                underlying, cur,
                entry_time_ist=entry_time_ist,
                eod_close_time_ist=eod_close_time_ist,
                short_strike_offset=short_strike_offset,
                long_strike_offset=long_strike_offset,
                stop_credit_multiple=stop_credit_multiple,
            )
            trades.append(t)
        cur += timedelta(days=1)

    entered = [t for t in trades if t.exit_reason in ("STOP", "EOD", "EOD_DATA_TRUNC")]
    stopped = [t for t in entered if t.exit_reason == "STOP"]
    eod = [t for t in entered if t.exit_reason == "EOD"]
    wins = [t for t in entered if (t.pnl or 0) > 0]

    roi_trades = [
        {"date": t.date, "entry_prem": t.entry_credit, "exit_prem": t.exit_debit,
         "status": "TP" if (t.pnl or 0) > 0 else "SL",
         "pnl_pct": t.pnl_pct or 0, "qty_lots": 1}
        for t in entered
    ]
    roi = compute_roi(roi_trades, starting_capital=starting_capital, lot_size=lot_size)

    return {
        "underlying": underlying,
        "window": [start_date.isoformat(), end_date.isoformat()],
        "params": {
            "entry_time_ist": entry_time_ist.strftime("%H:%M"),
            "eod_close_time_ist": eod_close_time_ist.strftime("%H:%M"),
            "short_strike_offset": short_strike_offset,
            "long_strike_offset": long_strike_offset,
            "stop_credit_multiple": stop_credit_multiple,
        },
        "trading_days": len(trades),
        "entered": len(entered),
        "stopped_out": len(stopped),
        "exited_eod": len(eod),
        "wins": len(wins),
        "win_rate": round(len(wins) / len(entered), 3) if entered else None,
        "total_pnl_inr_per_lot": round(sum(t.pnl or 0 for t in entered), 2),
        "total_pnl_inr": round(sum(t.pnl or 0 for t in entered) * lot_size, 2),
        "roi": roi,
        "trades": [asdict(t) for t in trades],
    }
