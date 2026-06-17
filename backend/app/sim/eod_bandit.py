"""EOD-style contextual bandit trained on NSE Bhavcopy.

Different beast from the intraday RL bandit:
  * One bar = one trading day
  * Features are EOD-derivable: PCR, PCR change, ATM momentum, DTE
  * Reward is the (TP/SL/TIMEOUT) outcome of buying ATM CE/PE and holding
    up to `max_hold_days` trading days with bracket exit, exactly like
    `simulate_eod`.

Trains via REINFORCE-style update on `app.rl.policy.Policy` with a 4-dim
feature vector. Persists into a fresh table `rl_policy_eod` so it doesn't
collide with the intraday bandit.
"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, OptionEod, RLPolicy
from app.rl.policy import Policy, ACTIONS
from app.rl.features import FEATURE_DIM as POLICY_DIM
from app.sim.engine import reward_for, compute_roi

log = logging.getLogger("reyu.sim.eod_bandit")


EOD_FEATURE_NAMES = [
    "pcr_oi",
    "pcr_change_dod",
    "atm_change_dod_pct",
    "dte_norm",
]
EOD_FEATURE_DIM = len(EOD_FEATURE_NAMES)


# ── Feature extraction ─────────────────────────────────────────────
@dataclass
class EodBar:
    trade_date: date
    expiry: datetime
    atm_strike: float
    pcr_oi: float
    atm_ce: dict
    atm_pe: dict
    dte: int


async def _load_window(
    s: AsyncSession, underlying: str, start: date, end: date,
) -> list[OptionEod]:
    rows = (await s.execute(
        select(OptionEod).where(
            OptionEod.underlying == underlying,
            OptionEod.trade_date.between(
                datetime.combine(start, datetime.min.time()),
                datetime.combine(end, datetime.max.time()),
            ),
        )
    )).scalars().all()
    return rows


def _index_by_day(rows: list[OptionEod]) -> dict:
    """Returns {date: {expiry: {strike: {CE: row, PE: row}}}} for O(1) ATM lookup."""
    out: dict = {}
    for r in rows:
        d = r.trade_date.date() if hasattr(r.trade_date, "date") else r.trade_date
        out.setdefault(d, {}).setdefault(r.expiry, {}).setdefault(r.strike, {})[r.option_type] = r
    return out


def _find_atm(by_strike: dict) -> tuple[float | None, dict, dict]:
    """ATM via min |CE_close - PE_close| over strikes that have both."""
    cands = []
    for k, pair in by_strike.items():
        ce, pe = pair.get("CE"), pair.get("PE")
        if ce and pe and ce.close > 0 and pe.close > 0:
            cands.append((k, abs(ce.close - pe.close), ce, pe))
    if not cands:
        return None, {}, {}
    k, _, ce, pe = min(cands, key=lambda x: x[1])
    return k, ce, pe


def _build_bars(
    idx: dict, only_dte_le: int = 14,
) -> list[EodBar]:
    """One EodBar per (date, nearest valid expiry, ATM)."""
    bars: list[EodBar] = []
    for d in sorted(idx.keys()):
        # Nearest expiry >= d with both CE+PE near ATM
        expiries = sorted([ex for ex in idx[d].keys() if ex.date() >= d])
        for ex in expiries:
            atm, ce_row, pe_row = _find_atm(idx[d][ex])
            if atm is None:
                continue
            dte = (ex.date() - d).days
            if dte > only_dte_le or dte < 1:
                continue
            # Aggregate PCR across the whole expiry
            ce_oi = sum(p["CE"].oi for p in idx[d][ex].values() if "CE" in p) or 1
            pe_oi = sum(p["PE"].oi for p in idx[d][ex].values() if "PE" in p) or 1
            pcr = pe_oi / ce_oi
            bars.append(EodBar(
                trade_date=d, expiry=ex, atm_strike=atm,
                pcr_oi=pcr,
                atm_ce={"open": ce_row.open, "high": ce_row.high,
                        "low": ce_row.low, "close": ce_row.close},
                atm_pe={"open": pe_row.open, "high": pe_row.high,
                        "low": pe_row.low, "close": pe_row.close},
                dte=dte,
            ))
            break       # one bar per day
    return bars


def _features_for(bar: EodBar, prev_bar: EodBar | None) -> list[float]:
    """Build the 4-dim signal feature vector + pad to Policy.FEATURE_DIM
    with zeros so the shared Policy class can score it.

    The Policy's normalisation will EWMA-smooth real dims; the zero-padded
    dims stay at 0 and their weights stay near 0 — no functional effect
    but keeps the signature compatible with the existing bandit code."""
    pcr_change = 0.0
    atm_change = 0.0
    if prev_bar is not None:
        if prev_bar.pcr_oi:
            pcr_change = bar.pcr_oi - prev_bar.pcr_oi
        if prev_bar.atm_strike:
            atm_change = (bar.atm_strike / prev_bar.atm_strike - 1.0) * 100
    signal = [bar.pcr_oi, pcr_change, atm_change, bar.dte / 14.0]
    return signal + [0.0] * (POLICY_DIM - len(signal))


# ── Forward simulation for one bar (uses bar.idx forward dates) ───
def _simulate_trade(
    action: str, entry_bar: EodBar,
    forward_bars_same_expiry: list[EodBar],
    target_pct: float, stop_pct: float,
) -> tuple[str, float, float]:
    """Returns (status, entry_prem, exit_prem)."""
    opt = "CE" if action == "LONG" else "PE"
    entry_prem = entry_bar.atm_ce["close"] if opt == "CE" else entry_bar.atm_pe["close"]
    if entry_prem <= 1:
        return "SKIP", 0.0, 0.0
    tp = entry_prem * (1 + target_pct)
    sl = entry_prem * (1 - stop_pct)

    exit_prem = entry_prem
    for fb in forward_bars_same_expiry:
        leg = fb.atm_ce if opt == "CE" else fb.atm_pe
        # Bracket via daily high/low at this leg
        if leg["high"] >= tp:
            return "TP", entry_prem, tp
        if leg["low"] <= sl:
            return "SL", entry_prem, sl
        exit_prem = leg["close"]
    return "TIMEOUT", entry_prem, exit_prem


# ── Train / test driver ────────────────────────────────────────────
async def train_test_eod_bandit(
    underlying: str,
    *,
    train_start: date, train_end: date,
    test_start: date, test_end: date,
    target_pct: float = 0.25, stop_pct: float = 0.15,
    max_hold_days: int = 5,
    only_dte_le: int = 14,
    epsilon: float = 0.10,
    lr: float = 0.10,
    epochs: int = 1,
    min_conviction: float = 0.0,
    starting_capital: float = 100_000,
    lot_size: int = 65,
    seed: int | None = None,
    persist: bool = False,
) -> dict:
    """End-to-end: fit a policy on `train_*`, evaluate read-only on `test_*`.
    Reports train + test metrics and a fitted weight dump.

    If `persist=True`, upserts the fitted Policy into `rl_policy` (keyed
    by underlying). The live RL_BANDIT strategy reads from there, so this
    is how a trained EOD policy gets shipped."""
    if seed is not None:
        random.seed(seed)

    async with SessionLocal() as s:
        all_rows = await _load_window(s, underlying, train_start, test_end)
    log.info("eod_bandit load: %d rows %s..%s", len(all_rows), train_start, test_end)
    idx = _index_by_day(all_rows)
    bars = _build_bars(idx, only_dte_le=only_dte_le)

    train_bars = [b for b in bars if train_start <= b.trade_date <= train_end]
    test_bars = [b for b in bars if test_start <= b.trade_date <= test_end]

    pol = Policy()
    # ── TRAIN ─────────────────────────────────────────────────────
    for ep in range(epochs):
        prev = None
        for i, bar in enumerate(train_bars):
            feats = _features_for(bar, prev)
            action_idx, _lp, _p = pol.act(feats, epsilon, min_conviction=min_conviction)
            action = ACTIONS[action_idx]
            if action == "FLAT":
                prev = bar
                continue
            # Forward bars sharing the same expiry, max_hold_days
            forward = [b for b in train_bars[i + 1:i + 1 + max_hold_days]
                       if b.expiry == bar.expiry]
            status, entry, ext = _simulate_trade(
                action, bar, forward, target_pct, stop_pct,
            )
            if status == "SKIP":
                prev = bar
                continue
            pnl_pct = (ext / entry - 1.0) * 100
            reward = reward_for(status, pnl_pct, target_pct, stop_pct)
            pol.update(feats, action_idx, reward, lr=lr)
            prev = bar

    train_n_trades = pol.n_updates

    # ── TEST (epsilon=0, greedy + conviction) ────────────────────
    test_trades = []
    prev = None
    for i, bar in enumerate(test_bars):
        feats = _features_for(bar, prev)
        scs = pol.scores(feats)
        probs = Policy._softmax(scs)
        a = max(range(3), key=lambda j: probs[j])
        if a in (0, 1) and min_conviction > 0:
            if probs[a] - probs[2] < min_conviction:
                a = 2
        if ACTIONS[a] == "FLAT":
            prev = bar; continue
        forward = [b for b in test_bars[i + 1:i + 1 + max_hold_days]
                   if b.expiry == bar.expiry]
        status, entry, ext = _simulate_trade(
            ACTIONS[a], bar, forward, target_pct, stop_pct,
        )
        if status == "SKIP":
            prev = bar; continue
        test_trades.append({
            "date": bar.trade_date.isoformat(),
            "action": ACTIONS[a],
            "entry_prem": entry, "exit_prem": ext,
            "status": status,
            "pnl_pct": (ext / entry - 1.0) * 100,
            "qty_lots": 1,
        })
        prev = bar

    n = len(test_trades)
    wins = sum(1 for t in test_trades if t["status"] == "TP")
    roi = compute_roi(test_trades, starting_capital=starting_capital,
                      lot_size=lot_size)

    persisted = False
    if persist:
        async with SessionLocal() as s2:
            row = (await s2.execute(
                select(RLPolicy).where(RLPolicy.underlying == underlying)
            )).scalar_one_or_none()
            if row is None:
                row = RLPolicy(underlying=underlying, epsilon=epsilon, enabled=True)
                s2.add(row)
            row.weights = pol.to_json()
            row.epsilon = epsilon
            row.target_pct = target_pct
            row.stop_pct = stop_pct
            row.last_trained_at = datetime.utcnow()
            row.n_trades = (row.n_trades or 0) + train_n_trades
            row.n_wins = (row.n_wins or 0) + wins
            row.enabled = True
            await s2.commit()
        persisted = True
        log.info("eod_bandit: persisted policy for %s (train_n=%d, test_n=%d, test_roi=%.2f%%)",
                 underlying, train_n_trades, n, roi.get("roi_pct", 0))

    return {
        "underlying": underlying,
        "train_window": [train_start.isoformat(), train_end.isoformat()],
        "test_window": [test_start.isoformat(), test_end.isoformat()],
        "train_bars": len(train_bars),
        "train_updates": train_n_trades,
        "test_bars": len(test_bars),
        "test_trades": n,
        "test_wins": wins,
        "test_win_rate": round(wins / n, 3) if n else None,
        "roi": roi,
        "feature_names": EOD_FEATURE_NAMES,
        "feature_mean": pol.mu,
        "feature_std": pol.sigma,
        "w_long": pol.w_long,
        "w_short": pol.w_short,
        "b_long": pol.b_long,
        "b_short": pol.b_short,
        "baseline": pol.baseline,
        "persisted_to_rl_policy": persisted,
    }
