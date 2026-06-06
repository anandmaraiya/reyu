"""Historical training loop using Fyers candle history.

We can't recover historical option chains (Fyers doesn't expose them), so
we synthesise synthetic ATM CE/PE trades using Black-Scholes pricing.
This is far from perfect for cross-strike effects but is exactly the right
training signal for a *directional* ATM bandit: the spot moves dominate
the premium, and the BS price will follow.

Procedure for each historical session:
  1. Pull 5-min candles for the underlying from Fyers.
  2. Compute realised intraday volatility → use as IV for BS pricing.
  3. Round spot at each bar to the nearest 50/100 strike → the "ATM" strike.
  4. At every bar (except the last few), the policy:
       a. Observes a feature vector derived from candle stats (no OI yet).
       b. Picks LONG / SHORT / FLAT with ε-greedy.
       c. If LONG/SHORT, the trade is simulated forward bar-by-bar:
          premium_t = BS_price(spot_t, strike, T_remaining, iv)
          Exit on first bar where premium crosses TP or SL, else timeout
          at session close.
       d. Reward computed via env.reward_for(). Policy.update() applied.

This generates O(50 trades/session × N sessions) training tuples per
underlying. ~30 trading days × 8 trades each ≈ 240 trades per symbol —
enough for the linear bandit to learn meaningful weights.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
import asyncio
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.greeks import bs_price
from app.db import RLPolicy
from app.rl.calendar import iter_trading_days
from app.rl.env import DEFAULT_TARGET_PCT, DEFAULT_STOP_PCT, reward_for
from app.rl.features import FEATURE_DIM
from app.rl.policy import Policy, ACTIONS, adjusted_epsilon
from app.fyers import client as fy

log = logging.getLogger("reyu.rl.backfill")
IST = timezone(timedelta(hours=5, minutes=30))

# ── Retry helper for Fyers API rate limits ──────────────────────
async def _fetch_history_with_retry(
    underlying: str,
    resolution: str,
    range_from: str,
    range_to: str,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> dict:
    """Fetch Fyers history with exponential backoff on failure."""
    for attempt in range(max_retries):
        try:
            return await fy.history(underlying, resolution=resolution,
                                     range_from=range_from, range_to=range_to)
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                log.warning("history %s %s failed (attempt %d/%d): %s — retrying in %.1fs",
                            underlying, range_from, attempt + 1, max_retries, e, delay)
                await asyncio.sleep(delay)
            else:
                log.warning("history %s %s failed after %d attempts: %s",
                            underlying, range_from, max_retries, e)
                raise


# ── Strike rounding heuristics per underlying ────────────────────
def _strike_step(underlying: str) -> float:
    u = underlying.upper()
    if "NIFTY50" in u or "NIFTYNXT" in u:
        return 50
    if "BANKNIFTY" in u or "BANKEX" in u:
        return 100
    if "FINNIFTY" in u or "MIDCP" in u:
        return 50
    if "SENSEX" in u:
        return 100
    if "-EQ" in u:
        # Stock options: 1% of price is a reasonable round, snap to multiples of 5
        return 5
    return 50


def _atm_strike(spot: float, step: float) -> float:
    return round(spot / step) * step


# ── Backfill feature vector — uses what we can recover from candles only.
# Layout matches FEATURE_NAMES from features.py: the chain-only features
# (PCR / OI / IV / max-pain) are filled with neutrals so the policy
# learns to weight them via the running stats normalisation.
def _backfill_features(candles_so_far: list[list], session_open_close: float | None,
                       progress: float) -> list[float]:
    last = candles_so_far[-1]
    spot = last[4]
    open_today = candles_so_far[0][1]
    open_5m = candles_so_far[-2][4] if len(candles_so_far) >= 2 else spot
    open_30m = candles_so_far[-7][4] if len(candles_so_far) >= 7 else spot
    prev_close = session_open_close if session_open_close else open_today

    # Realised vol of the last 12 5-min bars → proxy ATM IV
    recent_returns = []
    for i in range(max(0, len(candles_so_far) - 12), len(candles_so_far) - 1):
        c0 = candles_so_far[i][4]
        c1 = candles_so_far[i + 1][4]
        if c0 > 0:
            recent_returns.append(math.log(c1 / c0))
    if len(recent_returns) >= 3:
        sd = statistics.pstdev(recent_returns)
        # Annualise: √(252 trading days × 75 5-min bars per day) ≈ √18900
        atm_iv = sd * math.sqrt(252 * 75)
    else:
        atm_iv = 0.15

    legacy = [
        (spot / prev_close - 1.0) * 100 if prev_close else 0.0,  # spot_change_today
        (spot / open_5m - 1.0) * 100,                              # spot_5m
        (spot / open_30m - 1.0) * 100,                             # spot_30m
        0.0, 0.0, 0.0, 0.0,                                        # pcr (4 dims, unavailable)
        0.0, 0.0,                                                  # CE/PE OI deltas
        0.0,                                                       # OI imbalance
        atm_iv,                                                    # atm_iv
        0.0,                                                       # iv_change_30m
        0.0,                                                       # iv_skew
        0.0,                                                       # max_pain_distance
        0.0,                                                       # max_pain_drift
        progress,                                                  # session_progress
        0.0,                                                       # bias_score
        1.0,                                                       # snapshots_today (saturated)
    ]
    # ATM-band features (dims 18..29) — Fyers does not expose historical
    # option chains so we zero-pad here. Once OptionStrikeSnapshot has
    # accumulated history we'll swap in a replay-based backfill that
    # populates these properly; the policy will then re-learn weights for
    # them. For now the bandit lives off the candle-derived block.
    band_pad = [0.0] * (FEATURE_DIM - len(legacy))
    return legacy + band_pad


@dataclass
class BackfillStats:
    underlying: str
    sessions: int
    trades: int
    wins: int
    losses: int
    timeouts: int
    cum_reward: float


async def _simulate_session(
    candles_5m: list[list],
    pol: Policy,
    target_pct: float, stop_pct: float,
    epsilon: float,
    underlying: str,
    min_conviction: float = 0.0,
    lr: float | None = None,
    weight_decay: float = 0.0,
) -> tuple[list[dict], int, int, int, float]:
    """Replay one trading day. Returns (trade_dicts, wins, losses, timeouts, cum_reward)."""
    if len(candles_5m) < 10:
        return [], 0, 0, 0, 0.0
    step = _strike_step(underlying)
    open_close_prev = None

    trade_dicts: list[dict] = []
    wins = losses = timeouts = 0
    cum_reward = 0.0
    # Skip the final 4 bars (~20 minutes) so the policy always has room to
    # see a TP/SL before timeout.
    for idx in range(6, len(candles_5m) - 4):
        progress = idx / len(candles_5m)
        features = _backfill_features(candles_5m[:idx + 1], open_close_prev, progress)
        action_idx, _logprob, _probs = pol.act(features, epsilon, min_conviction=min_conviction)
        action = ACTIONS[action_idx]
        if action == "FLAT":
            continue

        # Simulate forward
        spot_entry = candles_5m[idx][4]
        strike = _atm_strike(spot_entry, step)
        opt = "CE" if action == "LONG" else "PE"
        # Constant DTE assumption: weekly expiry, ~3 days
        T_entry = 3 / 365
        iv = max(features[10], 0.05)        # atm_iv from features
        entry_prem = bs_price(spot_entry, strike, T_entry, 0.07, iv, opt)
        if entry_prem <= 0.5:               # too cheap → ratio noise, skip
            continue
        tp_prem = entry_prem * (1 + target_pct)
        sl_prem = entry_prem * (1 - stop_pct)

        status = "TIMEOUT"; exit_prem = entry_prem
        for j in range(idx + 1, min(idx + 30, len(candles_5m))):     # max 30 bars = 2.5h
            spot_j = candles_5m[j][4]
            T_j = max(T_entry - (j - idx) * 5 / (60 * 24 * 365), 1 / 365 / 24)
            prem_j = bs_price(spot_j, strike, T_j, 0.07, iv, opt)
            if prem_j >= tp_prem:
                status = "TP"; exit_prem = prem_j; break
            if prem_j <= sl_prem:
                status = "SL"; exit_prem = prem_j; break
            exit_prem = prem_j

        pnl_pct = (exit_prem / entry_prem - 1.0) * 100
        reward = reward_for(status, pnl_pct, target_pct, stop_pct)
        pol.update(features, action_idx, reward, lr=lr, weight_decay=weight_decay)
        trade_dicts.append({
            "entry_idx": idx, "exit_idx": j,
            "entry_prem": entry_prem, "exit_prem": exit_prem,
            "action": action, "status": status,
            "pnl_pct": pnl_pct, "reward": reward,
        })
        cum_reward += reward
        if status == "TP":
            wins += 1
        elif status == "SL":
            losses += 1
        else:
            timeouts += 1

    return trade_dicts, wins, losses, timeouts, cum_reward


async def backfill_underlying(
    s: AsyncSession,
    underlying: str,
    days: int = 30,
    epsilon: float | None = None,
    reset_policy: bool = False,
) -> BackfillStats:
    """Pull `days` trading days of 5-min history, train the policy on it.
    If `reset_policy` is True, wipe existing weights first."""
    # Load or initialise policy
    row = (await s.execute(select(RLPolicy).where(RLPolicy.underlying == underlying))).scalar_one_or_none()
    if row is None:
        row = RLPolicy(underlying=underlying, weights="{}",
                       epsilon=0.10, enabled=True,
                       target_pct=DEFAULT_TARGET_PCT, stop_pct=DEFAULT_STOP_PCT)
        s.add(row)
        await s.flush()
    if reset_policy:
        row.weights = "{}"; row.n_trades = 0; row.n_wins = 0; row.cum_reward = 0.0
    pol = Policy.from_json(row.weights)
    target_pct = row.target_pct or DEFAULT_TARGET_PCT
    stop_pct = row.stop_pct or DEFAULT_STOP_PCT
    eps = epsilon if epsilon is not None else (row.epsilon or 0.10)

    today = datetime.utcnow().date()
    start = today - timedelta(days=days + 10)        # extra slack for weekends

    sessions = trades = wins = losses = timeouts = 0
    cum_reward = 0.0

    for d in iter_trading_days(start, today - timedelta(days=1)):
        try:
            hist = await _fetch_history_with_retry(
                underlying, resolution="5",
                range_from=d.isoformat(), range_to=d.isoformat())
        except Exception as e:
            log.warning("history %s %s failed: %s", underlying, d, e)
            continue
        candles = hist.get("candles") or []
        if len(candles) < 10:
            continue
        sessions += 1
        tr_dicts, w, l, to, r = await _simulate_session(
            candles, pol, target_pct, stop_pct, eps, underlying
        )
        trades += len(tr_dicts); wins += w; losses += l; timeouts += to; cum_reward += r

    # Save updated policy
    row.weights = pol.to_json()
    row.n_trades = (row.n_trades or 0) + trades
    row.n_wins = (row.n_wins or 0) + wins
    row.cum_reward = (row.cum_reward or 0) + cum_reward
    row.last_trained_at = datetime.utcnow()
    await s.commit()

    log.info("backfill %s: %d sessions, %d trades, wins=%d losses=%d timeouts=%d cum=%.2f",
             underlying, sessions, trades, wins, losses, timeouts, cum_reward)
    return BackfillStats(underlying, sessions, trades, wins, losses, timeouts, cum_reward)


# ── No-concurrent simulator + ROI ───────────────────────────────────
# Mirrors live behaviour: at most one open trade at a time per underlying.
# Returns a list of trade dicts so a downstream ROI pass can sequence
# capital correctly. `train=True` calls policy.update() per closed trade.

def _seq_simulate_session(
    candles_5m: list[list],
    pol: Policy,
    target_pct: float, stop_pct: float,
    epsilon: float,
    underlying: str,
    *,
    min_conviction: float = 0.0,
    train: bool = False,
    lr: float | None = None,
    weight_decay: float = 0.0,
) -> list[dict]:
    if len(candles_5m) < 10:
        return []
    step = _strike_step(underlying)
    trades: list[dict] = []
    idx = 6
    last = len(candles_5m) - 4
    while idx < last:
        progress = idx / len(candles_5m)
        features = _backfill_features(candles_5m[:idx + 1], None, progress)
        if train:
            action_idx, _lp, _p = pol.act(features, epsilon, min_conviction=min_conviction)
        else:
            sc = pol.scores(features)
            probs = Policy._softmax(sc)
            action_idx = max(range(3), key=lambda i: probs[i])
            if action_idx in (0, 1) and min_conviction > 0:
                if probs[action_idx] - probs[2] < min_conviction:
                    action_idx = 2
        action = ACTIONS[action_idx]
        if action == "FLAT":
            idx += 1
            continue
        # Open synthetic ATM trade
        spot_entry = candles_5m[idx][4]
        strike = _atm_strike(spot_entry, step)
        opt = "CE" if action == "LONG" else "PE"
        T_entry = 3 / 365
        iv = max(features[10], 0.05)
        entry_prem = bs_price(spot_entry, strike, T_entry, 0.07, iv, opt)
        if entry_prem <= 0.5:
            idx += 1
            continue
        tp_prem = entry_prem * (1 + target_pct)
        sl_prem = entry_prem * (1 - stop_pct)
        status = "TIMEOUT"; exit_prem = entry_prem; exit_idx = idx
        for j in range(idx + 1, min(idx + 30, len(candles_5m))):
            spot_j = candles_5m[j][4]
            T_j = max(T_entry - (j - idx) * 5 / (60 * 24 * 365), 1 / 365 / 24)
            prem_j = bs_price(spot_j, strike, T_j, 0.07, iv, opt)
            exit_idx = j
            if prem_j >= tp_prem:
                status = "TP"; exit_prem = prem_j; break
            if prem_j <= sl_prem:
                status = "SL"; exit_prem = prem_j; break
            exit_prem = prem_j
        pnl_pct = (exit_prem / entry_prem - 1.0) * 100
        reward = reward_for(status, pnl_pct, target_pct, stop_pct)
        if train:
            pol.update(features, action_idx, reward, lr=lr, weight_decay=weight_decay)
        trades.append({
            "entry_idx": idx, "exit_idx": exit_idx,
            "entry_prem": entry_prem, "exit_prem": exit_prem,
            "action": action, "status": status,
            "pnl_pct": pnl_pct, "reward": reward,
        })
        # ── No-concurrent rule: next entry can only happen after exit
        idx = exit_idx + 1
    return trades


def compute_roi(
    trades: list[dict],
    *,
    starting_capital: float = 100_000.0,
    lot_size: int = 65,
    brokerage_per_trade: float = 50.0,
) -> dict:
    """Sequence trades through a capital account. Buying premium only.
    Skips a trade if outlay exceeds available capital. Reports ROI %,
    final capital, max drawdown, and turnover."""
    capital = starting_capital
    peak = starting_capital
    max_dd = 0.0
    taken = skipped = wins = 0
    pnl_inr = 0.0
    equity = [capital]
    for t in trades:
        outlay = t["entry_prem"] * lot_size
        if outlay > capital:
            skipped += 1
            continue
        gross = (t["exit_prem"] - t["entry_prem"]) * lot_size
        net = gross - brokerage_per_trade
        capital += net
        pnl_inr += net
        equity.append(capital)
        taken += 1
        if net > 0:
            wins += 1
        if capital > peak:
            peak = capital
        if peak > 0:
            dd = (peak - capital) / peak * 100
            if dd > max_dd:
                max_dd = dd
    return {
        "starting_capital": starting_capital,
        "final_capital": round(capital, 2),
        "pnl_inr": round(pnl_inr, 2),
        "roi_pct": round((capital / starting_capital - 1) * 100, 2) if starting_capital else 0.0,
        "max_drawdown_pct": round(max_dd, 2),
        "trades_taken": taken,
        "trades_skipped_capital": skipped,
        "win_rate_inr": round(wins / taken, 3) if taken else None,
        "lot_size": lot_size,
        "brokerage_per_trade": brokerage_per_trade,
    }


# ── Train / test split + holdout evaluator ─────────────────────────
async def _evaluate_session(
    candles_5m: list[list],
    pol: Policy,
    target_pct: float, stop_pct: float,
    underlying: str,
    min_conviction: float = 0.0,
) -> dict[str, float]:
    """Like _simulate_session but read-only — epsilon=0, no policy update.
    Reports per-session stats including total %P&L (sum of pnl_pct)."""
    if len(candles_5m) < 10:
        return {"trades": 0, "wins": 0, "losses": 0, "timeouts": 0,
                "cum_reward": 0.0, "cum_pnl_pct": 0.0}
    step = _strike_step(underlying)

    trades = wins = losses = timeouts = 0
    cum_reward = 0.0
    cum_pnl_pct = 0.0

    for idx in range(6, len(candles_5m) - 4):
        progress = idx / len(candles_5m)
        features = _backfill_features(candles_5m[:idx + 1], None, progress)
        # Greedy (epsilon=0): pick the highest-score action and apply
        # the same conviction filter as live trading.
        sc = pol.scores(features)
        probs = Policy._softmax(sc)
        action_idx = max(range(3), key=lambda i: probs[i])
        if action_idx in (0, 1) and min_conviction > 0:
            if probs[action_idx] - probs[2] < min_conviction:
                action_idx = 2
        action = ACTIONS[action_idx]
        if action == "FLAT":
            continue

        spot_entry = candles_5m[idx][4]
        strike = _atm_strike(spot_entry, step)
        opt = "CE" if action == "LONG" else "PE"
        T_entry = 3 / 365
        iv = max(features[10], 0.05)
        entry_prem = bs_price(spot_entry, strike, T_entry, 0.07, iv, opt)
        if entry_prem <= 0.5:
            continue
        tp_prem = entry_prem * (1 + target_pct)
        sl_prem = entry_prem * (1 - stop_pct)

        status = "TIMEOUT"; exit_prem = entry_prem
        for j in range(idx + 1, min(idx + 30, len(candles_5m))):
            spot_j = candles_5m[j][4]
            T_j = max(T_entry - (j - idx) * 5 / (60 * 24 * 365), 1 / 365 / 24)
            prem_j = bs_price(spot_j, strike, T_j, 0.07, iv, opt)
            if prem_j >= tp_prem:
                status = "TP"; exit_prem = prem_j; break
            if prem_j <= sl_prem:
                status = "SL"; exit_prem = prem_j; break
            exit_prem = prem_j

        pnl_pct = (exit_prem / entry_prem - 1.0) * 100
        cum_reward += reward_for(status, pnl_pct, target_pct, stop_pct)
        cum_pnl_pct += pnl_pct
        trades += 1
        if status == "TP": wins += 1
        elif status == "SL": losses += 1
        else: timeouts += 1

    return {"trades": trades, "wins": wins, "losses": losses, "timeouts": timeouts,
            "cum_reward": cum_reward, "cum_pnl_pct": cum_pnl_pct}


@dataclass
class TrainTestResult:
    underlying: str
    train_window: tuple[str, str]
    test_window: tuple[str, str]
    train_trades: int
    train_wins: int
    train_win_rate: float | None
    train_cum_reward: float
    test_trades: int
    test_wins: int
    test_win_rate: float | None
    test_cum_reward: float
    test_cum_pnl_pct: float
    test_avg_pnl_per_trade: float | None


async def train_test_underlying(
    s: AsyncSession,
    underlying: str,
    total_days: int = 30,
    test_days: int = 7,
    min_conviction: float = 0.0,
    target_pct_override: float | None = None,
    stop_pct_override: float | None = None,
    *,
    lr: float | None = None,
    epochs: int = 1,
    starting_capital: float = 100_000.0,
    lot_size: int = 65,
    brokerage_per_trade: float = 50.0,
    sequential: bool = True,
    weight_decay: float = 0.0,
) -> TrainTestResult:
    """End-to-end evaluation:
        1. Wipe the policy.
        2. Train on days [today - total_days, today - test_days).
        3. Evaluate (epsilon=0, no updates) on the remaining test_days.
    Returns honest out-of-sample metrics. Per-call overrides let us A/B
    different bracket sizes and conviction thresholds without mutating
    the persisted policy config."""
    # Reset policy
    row = (await s.execute(select(RLPolicy).where(RLPolicy.underlying == underlying))).scalar_one_or_none()
    if row is None:
        row = RLPolicy(underlying=underlying, weights="{}", epsilon=0.10, enabled=True,
                       target_pct=DEFAULT_TARGET_PCT, stop_pct=DEFAULT_STOP_PCT)
        s.add(row)
        await s.flush()
    row.weights = "{}"; row.n_trades = 0; row.n_wins = 0; row.cum_reward = 0.0
    if target_pct_override is not None:
        row.target_pct = target_pct_override
    if stop_pct_override is not None:
        row.stop_pct = stop_pct_override
    pol = Policy()
    target_pct = row.target_pct or DEFAULT_TARGET_PCT
    stop_pct = row.stop_pct or DEFAULT_STOP_PCT
    eps = row.epsilon or 0.10

    today = datetime.utcnow().date()
    test_start = today - timedelta(days=test_days)
    train_start = today - timedelta(days=total_days + 10)
    train_end = test_start - timedelta(days=1)
    test_end = today - timedelta(days=1)

    # ── Fetch all candles up front so we can replay epochs without
    #    re-hitting Fyers per epoch (kinder to their rate limits).
    train_sessions: list[list] = []
    for d in iter_trading_days(train_start, train_end):
        try:
            hist = await _fetch_history_with_retry(
                underlying, resolution="5",
                range_from=d.isoformat(), range_to=d.isoformat())
        except Exception:
            continue
        candles = hist.get("candles") or []
        if len(candles) >= 10:
            train_sessions.append(candles)
    test_sessions: list[list] = []
    for d in iter_trading_days(test_start, test_end):
        try:
            hist = await _fetch_history_with_retry(
                underlying, resolution="5",
                range_from=d.isoformat(), range_to=d.isoformat())
        except Exception:
            continue
        candles = hist.get("candles") or []
        if len(candles) >= 10:
            test_sessions.append(candles)

    # ── TRAIN (N epochs over the same data so a low LR converges) ──
    train_trades_all: list[dict] = []
    for ep in range(epochs):
        ep_trades: list[dict] = []
        for candles in train_sessions:
            if sequential:
                tr = _seq_simulate_session(
                    candles, pol, target_pct, stop_pct, eps, underlying,
                    min_conviction=min_conviction, train=True, lr=lr,
                    weight_decay=weight_decay,
                )
            else:
                tr, _w, _l, _to, _r = await _simulate_session(
                    candles, pol, target_pct, stop_pct, eps, underlying,
                    min_conviction=min_conviction, lr=lr,
                    weight_decay=weight_decay,
                )
            ep_trades.extend(tr)
        # Only retain the last epoch's trades for stats reporting
        if ep == epochs - 1:
            train_trades_all = ep_trades

    train_n = len(train_trades_all)
    train_wins = sum(1 for t in train_trades_all if t["status"] == "TP")
    train_cum_reward = sum(t["reward"] for t in train_trades_all)

    row.weights = pol.to_json()
    row.n_trades = train_n; row.n_wins = train_wins; row.cum_reward = train_cum_reward
    row.last_trained_at = datetime.utcnow()
    await s.commit()

    # ── TEST (greedy, no updates, sequential to match live) ───────
    test_trades_all: list[dict] = []
    for candles in test_sessions:
        if sequential:
            tr = _seq_simulate_session(
                candles, pol, target_pct, stop_pct, 0.0, underlying,
                min_conviction=min_conviction, train=False,
            )
        else:
            tr, _w, _l, _to, _r = await _simulate_session(
                candles, pol, target_pct, stop_pct, 0.0, underlying,
                min_conviction=min_conviction,
            )
        test_trades_all.extend(tr)

    test_n = len(test_trades_all)
    test_wins = sum(1 for t in test_trades_all if t["status"] == "TP")
    test_cum_reward = sum(t["reward"] for t in test_trades_all)
    test_cum_pnl_pct = sum(t["pnl_pct"] for t in test_trades_all)

    roi = compute_roi(
        test_trades_all,
        starting_capital=starting_capital,
        lot_size=lot_size,
        brokerage_per_trade=brokerage_per_trade,
    )

    result = TrainTestResult(
        underlying=underlying,
        train_window=(train_start.isoformat(), train_end.isoformat()),
        test_window=(test_start.isoformat(), test_end.isoformat()),
        train_trades=train_n, train_wins=train_wins,
        train_win_rate=round(train_wins / train_n, 3) if train_n else None,
        train_cum_reward=round(train_cum_reward, 2),
        test_trades=test_n, test_wins=test_wins,
        test_win_rate=round(test_wins / test_n, 3) if test_n else None,
        test_cum_reward=round(test_cum_reward, 2),
        test_cum_pnl_pct=round(test_cum_pnl_pct, 2),
        test_avg_pnl_per_trade=round(test_cum_pnl_pct / test_n, 3) if test_n else None,
    )
    # attach ROI as a runtime attribute (TrainTestResult dataclass stays unchanged)
    setattr(result, "roi", roi)
    setattr(result, "lr", lr if lr is not None else 0.05)
    setattr(result, "epochs", epochs)
    return result
