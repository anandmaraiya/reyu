"""Regime-router paper-live execution.

Two jobs:
  morning_decision  — 09:25 IST → classify yesterday's regime, pick action,
                      capture entry prices, write OPEN row
  eod_close         — 15:20 IST → capture exit prices, compute pnl, mark TP/SL

Architecture choice — standalone scheduler job, NOT a strategy_spec:
  * Router is too different in shape (4-leg condor) to fit the existing
    single-leg RL_BANDIT strategy contract.
  * Self-contained table keeps the schema small and the lifecycle obvious.
  * UI is one card on /admin/data — no big new surface needed.

Classifier params match the backtest-validated config:
  trend_threshold_pct = 1.5    (best risk-adjusted)
  range_threshold_pct = 0.3
  pcr_band            = (0.7, 1.4)
  momentum_lookback   = 3 days

Optimal config from the param sweep: ROI/DD ratio 102.6 on 2019-24.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal, OptionEod, OptionStrikeSnapshot, RegimeRouterPaperTrade
from app.fyers import client as fy

log = logging.getLogger("reyu.regime_router_live")

IST = timezone(timedelta(hours=5, minutes=30))

# Optimal params from the 2019-24 sweep (ROI/DD = 102.6)
TREND_TH = 1.5
RANGE_TH = 0.3
PCR_LOW = 0.7
PCR_HIGH = 1.4
MOM_LOOKBACK = 3

# Condor leg offsets (NIFTY strike step = 50)
SHORT_OFFSET = 50      # OTM1
LONG_OFFSET = 400      # OTM8

UNDERLYINGS = ["NSE:NIFTY50-INDEX"]
LOT_SIZES = {"NSE:NIFTY50-INDEX": 65}


# ── Regime classifier (identical to backtest) ─────────────────────────
async def _get_recent_atm_history(s, underlying: str, lookback_days: int = 7) -> list:
    """Pull last N days of (date, atm_strike, pcr_oi) from option_eod."""
    cutoff = date.today() - timedelta(days=lookback_days * 2)  # buffer for weekends
    rows = (await s.execute(
        select(OptionEod).where(
            OptionEod.underlying == underlying,
            OptionEod.trade_date >= datetime.combine(cutoff, datetime.min.time()),
        )
    )).scalars().all()
    # Group by trade_date and find ATM = min(|CE_close - PE_close|) per day
    by_day: dict = {}
    for r in rows:
        d = r.trade_date.date() if hasattr(r.trade_date, "date") else r.trade_date
        by_day.setdefault(d, {}).setdefault(r.expiry, {}).setdefault(r.strike, {})[r.option_type] = r
    history: list = []
    for d in sorted(by_day.keys()):
        # Pick nearest expiry with both CE+PE
        expiries = sorted([ex for ex in by_day[d].keys() if ex.date() >= d])
        for ex in expiries:
            cands = []
            for k, pair in by_day[d][ex].items():
                ce, pe = pair.get("CE"), pair.get("PE")
                if ce and pe and ce.close > 0 and pe.close > 0:
                    cands.append((k, abs(ce.close - pe.close)))
            if not cands:
                continue
            atm = min(cands, key=lambda x: x[1])[0]
            ce_oi = sum(p["CE"].oi for p in by_day[d][ex].values() if "CE" in p) or 1
            pe_oi = sum(p["PE"].oi for p in by_day[d][ex].values() if "PE" in p) or 1
            pcr = pe_oi / ce_oi
            history.append({"date": d, "atm": atm, "pcr": pcr, "expiry": ex})
            break
    return history


def _classify(history: list) -> tuple[str, float]:
    """Returns (regime, mom_3d_pct). Identical to backtest classifier."""
    if len(history) < MOM_LOOKBACK + 1:
        return "FLAT", 0.0
    today_atm = history[-1]["atm"]
    ref_atm = history[-1 - MOM_LOOKBACK]["atm"] if len(history) > MOM_LOOKBACK else None
    if not ref_atm:
        return "FLAT", 0.0
    mom = (today_atm / ref_atm - 1.0) * 100
    pcr = history[-1]["pcr"]

    if mom >= TREND_TH:
        return "TREND_UP", mom
    if mom <= -TREND_TH:
        return "TREND_DOWN", mom
    if abs(mom) <= RANGE_TH and PCR_LOW <= pcr <= PCR_HIGH:
        return "SIDEWAYS", mom
    return "FLAT", mom


# ── Live price lookup (option_strike_snapshot) ────────────────────────
async def _get_live_premium(s, underlying: str, strike: float, option_type: str,
                            expiry: datetime, ref_ts: datetime | None = None) -> float | None:
    """Return latest LTP for (underlying, strike, expiry, CE|PE) from the
    forward-collected snapshot table. If ref_ts is provided, picks the
    snapshot closest BEFORE that time."""
    q = select(OptionStrikeSnapshot).where(
        OptionStrikeSnapshot.underlying == underlying,
        OptionStrikeSnapshot.strike == strike,
        OptionStrikeSnapshot.expiry == expiry,
    )
    if ref_ts:
        q = q.where(OptionStrikeSnapshot.ts <= ref_ts)
    q = q.order_by(OptionStrikeSnapshot.ts.desc()).limit(1)
    row = (await s.execute(q)).scalar_one_or_none()
    if not row:
        return None
    return row.ce_ltp if option_type == "CE" else row.pe_ltp


# ── Morning decision job ──────────────────────────────────────────────
async def morning_decision() -> dict:
    """Run at 09:25 IST — classify regime, write OPEN row(s) with entry
    premiums. Skips if Fyers in demo or no recent data."""
    if await fy.is_demo():
        log.info("regime-router morning: skipped — Fyers in demo mode")
        return {"skipped": "demo_mode"}

    today = datetime.now(IST).date()
    out: dict = {"date": today.isoformat(), "decisions": []}

    async with SessionLocal() as s:
        for underlying in UNDERLYINGS:
            existing = (await s.execute(
                select(RegimeRouterPaperTrade).where(
                    RegimeRouterPaperTrade.trade_date == datetime.combine(today, datetime.min.time()),
                    RegimeRouterPaperTrade.underlying == underlying,
                )
            )).scalar_one_or_none()
            if existing:
                out["decisions"].append({
                    "underlying": underlying,
                    "skipped": "already_decided_today",
                    "regime": existing.regime, "action": existing.action,
                })
                continue

            history = await _get_recent_atm_history(s, underlying, lookback_days=10)
            if len(history) < MOM_LOOKBACK + 1:
                out["decisions"].append({
                    "underlying": underlying,
                    "skipped": "insufficient_history",
                    "history_len": len(history),
                })
                continue

            regime, mom = _classify(history)
            atm = history[-1]["atm"]
            pcr = history[-1]["pcr"]
            expiry = history[-1]["expiry"]
            entry_ts = datetime.now(timezone.utc)

            # Decide legs based on regime
            legs: list[dict] = []
            action = "SKIP"
            entry_total = 0.0

            if regime == "TREND_UP":
                action = "LONG_CE"
                prem = await _get_live_premium(s, underlying, atm, "CE", expiry, entry_ts)
                if prem and prem > 1:
                    legs = [{"side": "BUY", "type": "CE", "strike": atm, "entry": prem}]
                    entry_total = prem
            elif regime == "TREND_DOWN":
                action = "LONG_PE"
                prem = await _get_live_premium(s, underlying, atm, "PE", expiry, entry_ts)
                if prem and prem > 1:
                    legs = [{"side": "BUY", "type": "PE", "strike": atm, "entry": prem}]
                    entry_total = prem
            elif regime == "SIDEWAYS":
                action = "IRON_CONDOR"
                sc = await _get_live_premium(s, underlying, atm + SHORT_OFFSET, "CE", expiry, entry_ts)
                sp = await _get_live_premium(s, underlying, atm - SHORT_OFFSET, "PE", expiry, entry_ts)
                lc = await _get_live_premium(s, underlying, atm + LONG_OFFSET, "CE", expiry, entry_ts)
                lp = await _get_live_premium(s, underlying, atm - LONG_OFFSET, "PE", expiry, entry_ts)
                if all(p and p > 0.05 for p in (sc, sp, lc, lp)):
                    credit = (sc + sp) - (lc + lp)
                    if credit > 0:
                        legs = [
                            {"side": "SELL", "type": "CE", "strike": atm + SHORT_OFFSET, "entry": sc},
                            {"side": "SELL", "type": "PE", "strike": atm - SHORT_OFFSET, "entry": sp},
                            {"side": "BUY",  "type": "CE", "strike": atm + LONG_OFFSET,  "entry": lc},
                            {"side": "BUY",  "type": "PE", "strike": atm - LONG_OFFSET,  "entry": lp},
                        ]
                        entry_total = credit
            # FLAT regime → no legs, status SKIP

            status = "OPEN" if legs else "SKIP"
            await s.execute(pg_insert(RegimeRouterPaperTrade).values(
                trade_date=datetime.combine(today, datetime.min.time()),
                underlying=underlying,
                regime=regime,
                action=action,
                mom_3d_pct=round(mom, 3),
                pcr_oi=round(pcr, 3),
                atm_strike=atm,
                legs_json=json.dumps(legs),
                entry_premium_total=round(entry_total, 2) if entry_total else None,
                lot_size=LOT_SIZES.get(underlying, 65),
                status=status,
                entry_ts=entry_ts,
            ).on_conflict_do_nothing())
            await s.commit()

            out["decisions"].append({
                "underlying": underlying,
                "regime": regime, "action": action,
                "mom_3d_pct": round(mom, 3), "pcr": round(pcr, 3),
                "atm": atm, "entry_premium": round(entry_total, 2) if entry_total else None,
                "legs": len(legs), "status": status,
            })
    log.info("regime-router morning: %s", out)
    return out


# ── EOD close job ─────────────────────────────────────────────────────
async def eod_close() -> dict:
    """Run at 15:20 IST — square off every OPEN row from today using
    latest snapshot prices. Computes pnl and marks TP/SL."""
    if await fy.is_demo():
        log.info("regime-router eod_close: skipped — Fyers in demo mode")
        return {"skipped": "demo_mode"}

    today = datetime.now(IST).date()
    out: dict = {"date": today.isoformat(), "closed": []}

    async with SessionLocal() as s:
        opens = (await s.execute(
            select(RegimeRouterPaperTrade).where(
                RegimeRouterPaperTrade.trade_date == datetime.combine(today, datetime.min.time()),
                RegimeRouterPaperTrade.status == "OPEN",
            )
        )).scalars().all()

        for row in opens:
            legs = json.loads(row.legs_json or "[]")
            # Match expiry from morning. Heuristic: latest snapshot's expiry
            # for this underlying — same as morning since intraday expiry
            # doesn't change.
            exit_ts = datetime.now(timezone.utc)
            exit_total_signed = 0.0       # SELL = receive at exit, BUY = pay
            ok = True
            for leg in legs:
                snap = (await s.execute(
                    select(OptionStrikeSnapshot).where(
                        OptionStrikeSnapshot.underlying == row.underlying,
                        OptionStrikeSnapshot.strike == leg["strike"],
                    ).order_by(OptionStrikeSnapshot.ts.desc()).limit(1)
                )).scalar_one_or_none()
                if not snap:
                    ok = False
                    break
                ltp = snap.ce_ltp if leg["type"] == "CE" else snap.pe_ltp
                if not ltp:
                    ok = False
                    break
                leg["exit"] = ltp
                # For LONG single-leg: exit_total = prem to receive (positive)
                # For CONDOR: exit_total = debit needed to flatten the spread
                if row.action == "IRON_CONDOR":
                    # Short = pay to buy back; long = receive to sell
                    sign = 1 if leg["side"] == "SELL" else -1
                    exit_total_signed += sign * ltp
                else:
                    # single-leg long: exit_total is the sale value
                    exit_total_signed += ltp
            if not ok:
                continue

            # P&L per lot
            if row.action == "IRON_CONDOR":
                # entry_credit (received) - exit_debit (paid to close)
                pnl_per_lot = (row.entry_premium_total or 0) - exit_total_signed
            else:
                # exit_sale - entry_cost
                pnl_per_lot = exit_total_signed - (row.entry_premium_total or 0)

            pnl_inr = pnl_per_lot * (row.lot_size or 65)
            status = "TP" if pnl_per_lot > 0 else "SL"

            row.exit_premium_total = round(exit_total_signed, 2)
            row.pnl_per_lot = round(pnl_per_lot, 2)
            row.pnl_inr = round(pnl_inr, 2)
            row.status = status
            row.exit_ts = exit_ts
            row.legs_json = json.dumps(legs)
            out["closed"].append({
                "underlying": row.underlying,
                "action": row.action,
                "entry_premium": row.entry_premium_total,
                "exit_premium": exit_total_signed,
                "pnl_inr": pnl_inr,
                "status": status,
            })
        await s.commit()
    log.info("regime-router eod_close: %s", out)
    return out
