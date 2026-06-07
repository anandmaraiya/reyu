"""End-of-day swing simulator powered by NSE Bhavcopy.

Compared to the intraday 5-min BS-synthetic simulator (`engine.py`), this:

  * Operates on **real** option premiums from `option_eod`
  * Decides direction at each day's close, holds for up to `max_hold_days`
  * Bracket detection uses Bhavcopy daily OHLC of the strike — TP fires
    if `high >= tp_premium`, SL fires if `low <= sl_premium`
  * Picks ATM via min(|CE_close - PE_close|) across near-money strikes
    of the nearest weekly expiry (put-call parity proxy — NIFTY futures
    not yet ingested)

This is the honest counterpart to the BS-synth backtest. ROI gap between
the two tells us how inflated synthetic pricing was.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Callable, Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, OptionEod
from app.sim.engine import compute_roi  # reuse capital-sequenced ROI

log = logging.getLogger("reyu.sim.eod_engine")


# ── EOD-style decision tuple ──────────────────────────────────────
@dataclass
class EodDecision:
    action: str        # LONG / SHORT / FLAT
    metadata: dict = None


# A decider sees: (trade_date, atm_strike, prior_history) and returns LONG/SHORT/FLAT.
EodDecideFn = Callable[[date, float, list[dict]], EodDecision]


# ── ATM resolution via put-call parity proxy ───────────────────────
async def _atm_for_date(
    s: AsyncSession, underlying: str, trade_date: date,
) -> tuple[float, datetime] | None:
    """Find ATM strike + expiry for `trade_date`. Picks the nearest
    weekly expiry, then the strike with smallest |CE_close - PE_close|."""
    nearest = (await s.execute(
        select(func.min(OptionEod.expiry)).where(
            OptionEod.underlying == underlying,
            OptionEod.trade_date == trade_date,
            OptionEod.expiry >= trade_date,
        )
    )).scalar()
    if not nearest:
        return None
    # Pull both sides for this date+expiry; pivot per strike
    rows = (await s.execute(
        select(OptionEod).where(
            OptionEod.underlying == underlying,
            OptionEod.trade_date == trade_date,
            OptionEod.expiry == nearest,
        )
    )).scalars().all()
    by_strike: dict[float, dict] = {}
    for r in rows:
        by_strike.setdefault(r.strike, {})[r.option_type] = r.close
    candidates = [
        (k, abs(v.get("CE", 0) - v.get("PE", 0)))
        for k, v in by_strike.items()
        if "CE" in v and "PE" in v and v["CE"] > 0 and v["PE"] > 0
    ]
    if not candidates:
        return None
    atm = min(candidates, key=lambda x: x[1])[0]
    return atm, nearest


async def _strike_ohlc(
    s: AsyncSession, underlying: str, trade_date: date, expiry: datetime,
    strike: float, opt_type: str,
) -> dict | None:
    """Daily OHLC for one (date, strike, side)."""
    r = (await s.execute(
        select(OptionEod).where(
            OptionEod.underlying == underlying,
            OptionEod.trade_date == trade_date,
            OptionEod.expiry == expiry,
            OptionEod.strike == strike,
            OptionEod.option_type == opt_type,
        )
    )).scalar_one_or_none()
    if not r:
        return None
    return {"open": r.open, "high": r.high, "low": r.low,
            "close": r.close, "volume": r.volume, "oi": r.oi}


# ── Spot proxy from put-call parity ────────────────────────────────
async def _spot_proxy(
    s: AsyncSession, underlying: str, trade_date: date,
    expiry: datetime, atm_strike: float, r_rate: float = 0.07,
) -> float | None:
    """S = K + (C - P) * exp(rT). Tighter near-ATM."""
    ce = (await s.execute(
        select(OptionEod.close).where(
            OptionEod.underlying == underlying,
            OptionEod.trade_date == trade_date,
            OptionEod.expiry == expiry,
            OptionEod.strike == atm_strike,
            OptionEod.option_type == "CE",
        )
    )).scalar()
    pe = (await s.execute(
        select(OptionEod.close).where(
            OptionEod.underlying == underlying,
            OptionEod.trade_date == trade_date,
            OptionEod.expiry == expiry,
            OptionEod.strike == atm_strike,
            OptionEod.option_type == "PE",
        )
    )).scalar()
    if ce is None or pe is None:
        return None
    T = max((expiry.date() - trade_date).days / 365, 1 / 365)
    import math
    return atm_strike + (ce - pe) * math.exp(r_rate * T)


# ── EOD simulator core ─────────────────────────────────────────────
@dataclass
class EodTrade:
    entry_date: date
    exit_date: date
    expiry: datetime
    strike: float
    option_type: str
    action: str
    entry_prem: float
    exit_prem: float
    status: str
    pnl_pct: float


async def simulate_eod(
    underlying: str,
    decide: EodDecideFn,
    *,
    start_date: date,
    end_date: date,
    target_pct: float = 0.25,
    stop_pct: float = 0.15,
    max_hold_days: int = 5,
    only_if_dte_le: int = 14,
) -> list[EodTrade]:
    """Bulk-load all OptionEod rows for the window in ONE query, then
    simulate in memory. Avoids hundreds of small queries — orders of
    magnitude faster, especially while Bhavcopy backfill is contending
    for DB locks."""
    log.info("simulate_eod %s [%s..%s]", underlying, start_date, end_date)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(OptionEod).where(
                OptionEod.underlying == underlying,
                OptionEod.trade_date.between(
                    datetime.combine(start_date, datetime.min.time()),
                    datetime.combine(end_date, datetime.max.time()),
                ),
            )
        )).scalars().all()
    log.info("loaded %d rows for %s", len(rows), underlying)

    # ── Index in memory ────────────────────────────────────────────
    # idx[(date, expiry, strike)] -> {"CE": row, "PE": row}
    idx: dict[tuple[date, datetime, float], dict[str, OptionEod]] = {}
    dates_seen: set[date] = set()
    for r in rows:
        td = r.trade_date.date() if hasattr(r.trade_date, "date") else r.trade_date
        idx.setdefault((td, r.expiry, r.strike), {})[r.option_type] = r
        dates_seen.add(td)
    dates_sorted = sorted(dates_seen)

    history: list[dict] = []
    trades: list[EodTrade] = []

    for entry_date in dates_sorted:
        # ── Find ATM for this date via put-call parity proxy ───────
        keys = [(d, ex, k) for (d, ex, k) in idx.keys() if d == entry_date]
        if not keys:
            continue
        # Group by expiry to find nearest valid one
        expiries = sorted({ex for (_, ex, _) in keys if ex.date() >= entry_date})
        atm = expiry = None
        for ex_candidate in expiries:
            cand_strikes = [k for (d, ex, k) in keys if ex == ex_candidate]
            valid = []
            for k in cand_strikes:
                pair = idx[(entry_date, ex_candidate, k)]
                if "CE" in pair and "PE" in pair and pair["CE"].close > 0 and pair["PE"].close > 0:
                    valid.append((k, abs(pair["CE"].close - pair["PE"].close)))
            if valid:
                atm = min(valid, key=lambda x: x[1])[0]
                expiry = ex_candidate
                break
        if atm is None:
            continue
        dte = (expiry.date() - entry_date).days
        if dte > only_if_dte_le or dte < 1:
            continue

        decision = decide(entry_date, atm, history)
        if decision.action == "FLAT":
            history.append({"date": entry_date, "atm": atm, "action": "FLAT"})
            continue

        opt = "CE" if decision.action == "LONG" else "PE"
        entry_pair = idx.get((entry_date, expiry, atm))
        if not entry_pair or opt not in entry_pair:
            continue
        entry_prem = entry_pair[opt].close
        if entry_prem <= 1:
            continue
        tp_prem = entry_prem * (1 + target_pct)
        sl_prem = entry_prem * (1 - stop_pct)

        # Track forward
        forward_dates = [d for d in dates_sorted if d > entry_date][:max_hold_days]
        status = "TIMEOUT"
        exit_prem = entry_prem
        exit_date = entry_date

        for fd in forward_dates:
            if fd > expiry.date():
                break
            pair = idx.get((fd, expiry, atm))
            if not pair or opt not in pair:
                continue
            row = pair[opt]
            exit_date = fd
            if row.high >= tp_prem:
                status = "TP"
                exit_prem = tp_prem
                break
            if row.low <= sl_prem:
                status = "SL"
                exit_prem = sl_prem
                break
            exit_prem = row.close

        pnl_pct = (exit_prem / entry_prem - 1.0) * 100
        trade = EodTrade(
            entry_date=entry_date, exit_date=exit_date,
            expiry=expiry, strike=atm, option_type=opt,
            action=decision.action, entry_prem=entry_prem,
            exit_prem=exit_prem, status=status, pnl_pct=pnl_pct,
        )
        trades.append(trade)
        history.append({"date": entry_date, "atm": atm,
                        "action": decision.action, "pnl_pct": pnl_pct})

    return trades


# ── Helpers to turn EodTrade list into compute_roi-ready dicts ─────
def trades_to_roi_dicts(trades: list[EodTrade]) -> list[dict]:
    return [{
        "entry_prem": t.entry_prem,
        "exit_prem": t.exit_prem,
        "qty_lots": 1,
    } for t in trades]
