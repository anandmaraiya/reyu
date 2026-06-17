"""Iron-condor EOD contextual bandit on Bhavcopy.

Strategy structure (NIFTY, strike step 50):
  SELL  ATM+50  CE  +  SELL  ATM-50  PE     (short OTM1 strangle)
  BUY   ATM+400 CE  +  BUY   ATM-400 PE     (long  OTM8 wings — hedge)

  Net entry = credit collected at day open (premium received - premium paid)
  Net exit  = same legs valued at day close
  P&L per condor = (entry net credit) - (exit net debit needed to flatten)

Strict EOD square-off: enter at day open, exit at day close, every trading day
the bandit chooses ENTER. No overnight risk.

RL action mapping (reusing 3-action `Policy`):
  LONG  → ENTER credit condor   (we expect range, vol crush)
  SHORT → unused (reserved for future "reverse condor" / long-vol play)
  FLAT  → skip the day

Features (4-dim signal padded to POLICY_DIM):
  pcr_oi          — yesterday's ATM-band PCR
  pcr_change_dod  — change in PCR vs day before
  atm_change_dod% — NIFTY momentum (proxy for vol regime)
  dte_norm        — DTE/14

Persists to rl_policy with underlying suffix "/IC" so it doesn't clobber
the directional single-leg bandit.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, OptionEod, RLPolicy
from app.rl.policy import Policy, ACTIONS
from app.rl.features import FEATURE_DIM as POLICY_DIM
from app.sim.engine import compute_roi

log = logging.getLogger("reyu.sim.iron_condor_eod")


IC_FEATURE_NAMES = [
    "pcr_oi",
    "pcr_change_dod",
    "atm_change_dod_pct",
    "dte_norm",
]


@dataclass
class IcBar:
    trade_date: date
    expiry: datetime
    atm_strike: float
    pcr_oi: float
    dte: int
    # full {strike: {CE:row, PE:row}} for this (date, expiry) — needed
    # so the simulator can pick OTM1/OTM8 strikes
    by_strike: dict


async def _load_window(
    s: AsyncSession, underlying: str, start: date, end: date,
) -> list[OptionEod]:
    return (await s.execute(
        select(OptionEod).where(
            OptionEod.underlying == underlying,
            OptionEod.trade_date.between(
                datetime.combine(start, datetime.min.time()),
                datetime.combine(end, datetime.max.time()),
            ),
        )
    )).scalars().all()


def _index_by_day(rows: list[OptionEod]) -> dict:
    out: dict = {}
    for r in rows:
        d = r.trade_date.date() if hasattr(r.trade_date, "date") else r.trade_date
        out.setdefault(d, {}).setdefault(r.expiry, {}).setdefault(r.strike, {})[r.option_type] = r
    return out


def _find_atm(by_strike: dict) -> tuple[float | None, dict, dict]:
    cands = []
    for k, pair in by_strike.items():
        ce, pe = pair.get("CE"), pair.get("PE")
        if ce and pe and ce.close > 0 and pe.close > 0:
            cands.append((k, abs(ce.close - pe.close), ce, pe))
    if not cands:
        return None, {}, {}
    k, _, ce, pe = min(cands, key=lambda x: x[1])
    return k, ce, pe


def _build_bars(idx: dict, only_dte_le: int = 14) -> list[IcBar]:
    bars: list[IcBar] = []
    for d in sorted(idx.keys()):
        expiries = sorted([ex for ex in idx[d].keys() if ex.date() >= d])
        for ex in expiries:
            atm, ce_row, pe_row = _find_atm(idx[d][ex])
            if atm is None:
                continue
            dte = (ex.date() - d).days
            if dte > only_dte_le or dte < 1:
                continue
            ce_oi = sum(p["CE"].oi for p in idx[d][ex].values() if "CE" in p) or 1
            pe_oi = sum(p["PE"].oi for p in idx[d][ex].values() if "PE" in p) or 1
            pcr = pe_oi / ce_oi
            bars.append(IcBar(
                trade_date=d, expiry=ex, atm_strike=atm,
                pcr_oi=pcr, dte=dte, by_strike=idx[d][ex],
            ))
            break
    return bars


def _features_for(bar: IcBar, prev: IcBar | None) -> list[float]:
    pcr_change = 0.0
    atm_change = 0.0
    if prev is not None:
        if prev.pcr_oi:
            pcr_change = bar.pcr_oi - prev.pcr_oi
        if prev.atm_strike:
            atm_change = (bar.atm_strike / prev.atm_strike - 1.0) * 100
    signal = [bar.pcr_oi, pcr_change, atm_change, bar.dte / 14.0]
    return signal + [0.0] * (POLICY_DIM - len(signal))


def _simulate_condor(
    bar: IcBar,
    *,
    short_strike_offset: int = 50,
    long_strike_offset: int = 400,
) -> tuple[str, float, float] | None:
    """Build the 4-leg condor at this bar's strikes. Returns
    (status, entry_credit, exit_debit) per condor (1 lot each leg).

    entry_credit > 0 → we got paid at open (short OTM1 > long OTM8)
    exit_debit         → cost to flatten at close
    P&L per condor    = entry_credit - exit_debit (positive = profit)

    Uses .open for entry, .close for exit (Bhavcopy day-bar approximation
    of an intraday entry-at-open / exit-at-close iron condor).
    """
    atm = bar.atm_strike
    short_call_k = atm + short_strike_offset
    short_put_k = atm - short_strike_offset
    long_call_k = atm + long_strike_offset
    long_put_k = atm - long_strike_offset

    legs = {
        "SC": bar.by_strike.get(short_call_k, {}).get("CE"),
        "SP": bar.by_strike.get(short_put_k, {}).get("PE"),
        "LC": bar.by_strike.get(long_call_k, {}).get("CE"),
        "LP": bar.by_strike.get(long_put_k, {}).get("PE"),
    }
    if not all(legs.values()):
        return None
    if any(l.open <= 0.05 for l in legs.values()):
        # Sub-paisa premium = stale row. Skip.
        return None

    entry_credit = (legs["SC"].open + legs["SP"].open
                    - legs["LC"].open - legs["LP"].open)
    exit_debit = (legs["SC"].close + legs["SP"].close
                  - legs["LC"].close - legs["LP"].close)

    if entry_credit <= 0:
        # Inverted — wings cost more than body. Skip.
        return None

    pnl = entry_credit - exit_debit
    if pnl > 0:
        status = "TP"
    elif pnl < 0:
        status = "SL"
    else:
        status = "FLAT"
    return status, entry_credit, exit_debit


def _reward_for_condor(pnl: float, entry_credit: float) -> float:
    """Symmetric reward in [-1, 1]. Scale by entry_credit so percentage
    moves matter, not absolute rupees."""
    if entry_credit <= 0:
        return 0.0
    r = pnl / entry_credit
    return max(-1.0, min(1.0, r))


# ── Train / test ───────────────────────────────────────────────────
async def train_test_iron_condor_bandit(
    underlying: str,
    *,
    train_start: date, train_end: date,
    test_start: date, test_end: date,
    short_strike_offset: int = 50,
    long_strike_offset: int = 400,
    only_dte_le: int = 14,
    epsilon: float = 0.10,
    lr: float = 0.10,
    epochs: int = 1,
    min_conviction: float = 0.05,
    starting_capital: float = 100_000,
    lot_size: int = 65,
    seed: int | None = None,
    persist: bool = False,
) -> dict:
    if seed is not None:
        random.seed(seed)

    async with SessionLocal() as s:
        all_rows = await _load_window(s, underlying, train_start, test_end)
    log.info("ic_bandit load: %d rows %s..%s", len(all_rows), train_start, test_end)
    idx = _index_by_day(all_rows)
    bars = _build_bars(idx, only_dte_le=only_dte_le)
    train_bars = [b for b in bars if train_start <= b.trade_date <= train_end]
    test_bars = [b for b in bars if test_start <= b.trade_date <= test_end]

    pol = Policy()
    # ── TRAIN ─────────────────────────────────────────────────────
    train_pnl = 0.0
    train_n_trades = 0
    for ep in range(epochs):
        prev = None
        for bar in train_bars:
            feats = _features_for(bar, prev)
            action_idx, _lp, _p = pol.act(feats, epsilon, min_conviction=min_conviction)
            action = ACTIONS[action_idx]
            if action != "LONG":
                prev = bar; continue
            sim = _simulate_condor(
                bar,
                short_strike_offset=short_strike_offset,
                long_strike_offset=long_strike_offset,
            )
            if sim is None:
                prev = bar; continue
            status, entry_credit, exit_debit = sim
            pnl_per_condor = entry_credit - exit_debit
            reward = _reward_for_condor(pnl_per_condor, entry_credit)
            pol.update(feats, action_idx, reward, lr=lr)
            train_pnl += pnl_per_condor * lot_size
            train_n_trades += 1
            prev = bar

    # ── TEST (greedy + conviction gate) ───────────────────────────
    test_trades = []
    prev = None
    for bar in test_bars:
        feats = _features_for(bar, prev)
        scs = pol.scores(feats)
        probs = Policy._softmax(scs)
        a = max(range(3), key=lambda j: probs[j])
        if a in (0, 1) and min_conviction > 0:
            if probs[a] - probs[2] < min_conviction:
                a = 2
        if ACTIONS[a] != "LONG":
            prev = bar; continue
        sim = _simulate_condor(
            bar,
            short_strike_offset=short_strike_offset,
            long_strike_offset=long_strike_offset,
        )
        if sim is None:
            prev = bar; continue
        status, entry_credit, exit_debit = sim
        pnl_per_condor = entry_credit - exit_debit
        # Express as a synthetic "trade" for the ROI engine. Treat the
        # condor as one premium-collection unit per lot: entry_prem =
        # entry_credit, exit_prem = exit_debit; pnl_pct = (entry - exit)
        # / entry. Single trade per day, qty=1 lot.
        pnl_pct = (entry_credit - exit_debit) / entry_credit * 100 if entry_credit > 0 else 0
        test_trades.append({
            "date": bar.trade_date.isoformat(),
            "action": "ENTER_CONDOR",
            "atm_strike": bar.atm_strike,
            "entry_prem": entry_credit,
            "exit_prem": exit_debit,
            "status": status,
            "pnl_pct": pnl_pct,
            "qty_lots": 1,
        })
        prev = bar

    n = len(test_trades)
    wins = sum(1 for t in test_trades if t["status"] == "TP")
    roi = compute_roi(test_trades, starting_capital=starting_capital,
                      lot_size=lot_size)

    persisted = False
    persist_key = f"{underlying}/IC"
    if persist:
        async with SessionLocal() as s2:
            row = (await s2.execute(
                select(RLPolicy).where(RLPolicy.underlying == persist_key)
            )).scalar_one_or_none()
            if row is None:
                row = RLPolicy(underlying=persist_key, epsilon=epsilon, enabled=True)
                s2.add(row)
            row.weights = pol.to_json()
            row.epsilon = epsilon
            row.target_pct = 0.0
            row.stop_pct = 0.0
            row.last_trained_at = datetime.utcnow()
            row.n_trades = (row.n_trades or 0) + train_n_trades
            row.n_wins = (row.n_wins or 0) + wins
            row.enabled = True
            await s2.commit()
        persisted = True
        log.info("ic_bandit: persisted policy at %s (train_n=%d, test_n=%d, test_roi=%.2f%%)",
                 persist_key, train_n_trades, n, roi.get("roi_pct", 0))

    return {
        "underlying": underlying,
        "persist_key": persist_key,
        "structure": {
            "short_otm_offset": short_strike_offset,
            "long_otm_offset": long_strike_offset,
            "legs": ["SHORT ATM+off CE", "SHORT ATM-off PE",
                     "LONG ATM+wing CE", "LONG ATM-wing PE"],
            "intraday_eod_square_off": True,
        },
        "train_window": [train_start.isoformat(), train_end.isoformat()],
        "test_window": [test_start.isoformat(), test_end.isoformat()],
        "train_bars": len(train_bars),
        "train_updates": train_n_trades,
        "train_total_pnl_inr": round(train_pnl, 2),
        "test_bars": len(test_bars),
        "test_trades": n,
        "test_wins": wins,
        "test_win_rate": round(wins / n, 3) if n else None,
        "roi": roi,
        "feature_names": IC_FEATURE_NAMES,
        "w_long": pol.w_long,
        "w_short": pol.w_short,
        "b_long": pol.b_long,
        "b_short": pol.b_short,
        "baseline": pol.baseline,
        "persisted_to_rl_policy": persisted,
    }
