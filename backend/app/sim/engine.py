"""Shared trade-simulation engine — Sprint 1.1.

Both the RL bandit and user-defined strategies decide trades through one
core loop. The only thing that varies between them is the `decide`
callable. This means:

  * Same TP/SL detection logic
  * Same MAE / MFE tracking
  * Same no-concurrent rule
  * Same friction model
  * Any future improvement (eg. bar-attribution fix, real-options pricer
    swap, regime-aware brackets) lands once and helps both consumers.

Three pluggable hooks:

  decide(features, bar_idx, ctx) -> Decision
      Drives entry. Bandit returns Policy.act(); CONDITIONAL strategy
      returns conditions.evaluate(); Buy-and-hold returns LONG forever.

  pricer(spot, strike, T_years, opt_type, ctx) -> float
      Computes the synthetic option premium. Default is the existing
      BS price; data-lake-aware strategies plug in
      `cache.get_strike_data` lookups instead.

  on_close(trade, features) -> None  [optional]
      Called per closed trade. RL uses this to drive `Policy.update()`
      with the realised reward.
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Callable, Any

from app.analytics.greeks import bs_price

# ── Public action vocabulary ────────────────────────────────────────
ACTIONS = ["LONG", "SHORT", "FLAT"]
N_ACTIONS = 3

# ── Reward shape (carried over from rl.env.reward_for) ──────────────
def reward_for(status: str, pnl_pct: float | None,
               target_pct: float, stop_pct: float) -> float:
    if status == "TP":
        return 1.0
    if status == "SL":
        return -(stop_pct / max(target_pct, 1e-6))
    if status == "TIMEOUT" and pnl_pct is not None:
        scaled = (pnl_pct / 100.0) / max(target_pct, 1e-6)
        return max(-1.0, min(1.0, scaled))
    return 0.0


# ── Strike rounding heuristics ──────────────────────────────────────
def strike_step(underlying: str) -> float:
    u = underlying.upper()
    if "NIFTY50" in u or "NIFTYNXT" in u or "FINNIFTY" in u or "MIDCP" in u:
        return 50
    if "BANKNIFTY" in u or "BANKEX" in u or "SENSEX" in u:
        return 100
    if "-EQ" in u:
        return 5
    return 50


def atm_strike(spot: float, step: float) -> float:
    return round(spot / step) * step


# ── Data classes ───────────────────────────────────────────────────
@dataclass
class Decision:
    action: str                     # LONG / SHORT / FLAT
    strike_offset: int = 0          # ATM ± N steps
    qty_lots: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimTrade:
    entry_idx: int
    exit_idx: int
    entry_prem: float
    exit_prem: float
    strike: float
    option_type: str                # CE / PE
    action: str                     # LONG / SHORT
    status: str                     # TP / SL / TIMEOUT
    pnl_pct: float
    reward: float
    qty_lots: int = 1
    entry_signal: dict[str, Any] = field(default_factory=dict)
    mae_pct: float = 0.0            # max adverse excursion (worst intra)
    mfe_pct: float = 0.0            # max favorable excursion (best intra)
    iv_used: float = 0.0


# ── Type aliases ───────────────────────────────────────────────────
DecideFn = Callable[[list[float], int, dict], Decision]
FeatureFn = Callable[[list[list], int], list[float]]
PricerFn = Callable[[float, float, float, str, dict], float]
OnCloseFn = Callable[[SimTrade, list[float]], None]


# ── Default BS pricer ──────────────────────────────────────────────
def bs_pricer(spot: float, strike: float, T: float, opt: str, ctx: dict) -> float:
    iv = ctx.get("iv", 0.15)
    return bs_price(spot, strike, T, 0.07, iv, opt)


# ── Realized-vol feature extractor (re-export of backfill heuristic) ─
def realized_iv_feature_extractor(
    candles_so_far: list[list], idx: int,
    *, lookback: int = 12, annualisation: float = 252 * 75,
) -> list[float]:
    """Returns the same 18-dim feature vector the RL backfill uses,
    derivable from candle data alone. Strategy backtests can plug a
    richer extractor in once the per-strike snapshot pipeline catches up."""
    spot = candles_so_far[idx][4]
    open_today = candles_so_far[0][1]
    open_5m = candles_so_far[idx - 1][4] if idx >= 1 else spot
    open_30m = candles_so_far[idx - 6][4] if idx >= 6 else spot

    rets = []
    for k in range(max(0, idx - lookback), idx):
        if k + 1 > idx: break
        c0 = candles_so_far[k][4]; c1 = candles_so_far[k + 1][4]
        if c0 > 0 and c1 > 0:
            rets.append(math.log(c1 / c0))
    iv = (statistics.pstdev(rets) * math.sqrt(annualisation)) if len(rets) >= 3 else 0.15

    progress = idx / max(1, len(candles_so_far))
    return [
        (spot / open_today - 1.0) * 100 if open_today else 0.0,
        (spot / open_5m - 1.0) * 100,
        (spot / open_30m - 1.0) * 100,
        0.0, 0.0, 0.0, 0.0,           # PCR slots — not available from candles
        0.0, 0.0, 0.0,                # OI / imbalance slots
        iv,
        0.0, 0.0, 0.0, 0.0,           # IV change, skew, max-pain
        progress,
        0.0, 1.0,                     # bias, snapshots_today
    ]


# ── Core: simulate one session ─────────────────────────────────────
def simulate_session(
    candles_5m: list[list],
    *,
    decide: DecideFn,
    target_pct: float,
    stop_pct: float,
    underlying: str,
    feature_extractor: FeatureFn = realized_iv_feature_extractor,
    pricer: PricerFn = bs_pricer,
    on_close: OnCloseFn | None = None,
    max_hold_bars: int = 30,
    bs_dte_days: float = 3.0,
    iv_floor: float = 0.05,
    seed: int | None = None,
) -> list[SimTrade]:
    """No-concurrent simulator: at most one open trade at a time.

    Returns a list of SimTrade. Caller can sequence them through
    `compute_roi` to get capital-aware ROI + drawdown."""
    if seed is not None:
        random.seed(seed)
    if len(candles_5m) < 10:
        return []
    step = strike_step(underlying)
    trades: list[SimTrade] = []
    idx = 6
    last = len(candles_5m) - 4
    while idx < last:
        features = feature_extractor(candles_5m, idx)
        ctx = {"progress": idx / len(candles_5m), "underlying": underlying}
        decision = decide(features, idx, ctx)
        if decision.action == "FLAT":
            idx += 1
            continue

        spot_entry = candles_5m[idx][4]
        strike = atm_strike(spot_entry, step) + decision.strike_offset * step
        opt = "CE" if decision.action == "LONG" else "PE"
        T_entry = bs_dte_days / 365
        iv = max(features[10] if len(features) > 10 else 0.15, iv_floor)
        # Pricer ctx: iv for BS, ts for real-data lookup (real_pricer needs it)
        entry_ts = candles_5m[idx][0]
        entry_prem = pricer(spot_entry, strike, T_entry, opt,
                            {"iv": iv, "ts": entry_ts})
        if entry_prem <= 0.5:
            idx += 1
            continue

        tp_prem = entry_prem * (1 + target_pct)
        sl_prem = entry_prem * (1 - stop_pct)
        status = "TIMEOUT"
        exit_prem = entry_prem
        exit_idx = idx
        max_fav = 0.0
        max_adv = 0.0

        for j in range(idx + 1, min(idx + max_hold_bars, len(candles_5m))):
            spot_j = candles_5m[j][4]
            T_j = max(T_entry - (j - idx) * 5 / (60 * 24 * 365), 1 / 365 / 24)
            prem_j = pricer(spot_j, strike, T_j, opt,
                            {"iv": iv, "ts": candles_5m[j][0]})
            move_pct = (prem_j / entry_prem - 1.0) * 100
            if move_pct > max_fav: max_fav = move_pct
            if move_pct < max_adv: max_adv = move_pct
            exit_idx = j
            if prem_j >= tp_prem:
                status = "TP"; exit_prem = prem_j; break
            if prem_j <= sl_prem:
                status = "SL"; exit_prem = prem_j; break
            exit_prem = prem_j

        pnl_pct = (exit_prem / entry_prem - 1.0) * 100
        reward = reward_for(status, pnl_pct, target_pct, stop_pct)
        trade = SimTrade(
            entry_idx=idx, exit_idx=exit_idx,
            entry_prem=entry_prem, exit_prem=exit_prem,
            strike=strike, option_type=opt,
            action=decision.action, status=status,
            pnl_pct=pnl_pct, reward=reward,
            qty_lots=decision.qty_lots,
            entry_signal=decision.metadata,
            mae_pct=round(max_adv, 3), mfe_pct=round(max_fav, 3),
            iv_used=iv,
        )
        trades.append(trade)
        if on_close:
            on_close(trade, features)
        idx = exit_idx + 1
    return trades


def simulate_session_multileg(
    candles_5m: list[list],
    *,
    gate: DecideFn,
    legs: list[dict],
    target_pct: float,
    stop_pct: float,
    underlying: str,
    feature_extractor: FeatureFn = realized_iv_feature_extractor,
    pricer: PricerFn = bs_pricer,
    max_hold_bars: int = 30,
    bs_dte_days: float = 3.0,
    iv_floor: float = 0.05,
    seed: int | None = None,
) -> list[SimTrade]:
    """Multi-leg intraday simulator — prices EVERY leg per bar and tracks the
    combined position, so real spreads (bull-put, iron-condor, ratio, …) are
    simulated as one net structure rather than just the primary leg.

    `gate(features, idx, ctx)` is the entry gate: a non-FLAT decision opens the
    full leg structure; the decision's direction/offset are ignored (the
    structure is fixed by `legs`). Each leg dict: {action BUY|SELL,
    option_type CE|PE, offset (ATM steps, int), qty_lots}.

    P&L convention: net mark-to-market = Σ sign·prem·qty (sign +1 BUY / −1 SELL).
    Position P&L vs entry = MTM_now − MTM_entry (works for both debit and credit
    structures). TP/SL fire on P&L as a fraction of |net entry premium| — the
    natural analog of the single-leg 'percent of entry premium'. Results fold
    the net basis into entry_prem/exit_prem so compute_roi + metrics work
    unchanged; per-leg detail rides in entry_signal['legs']."""
    if seed is not None:
        random.seed(seed)
    if len(candles_5m) < 10 or not legs:
        return []
    step = strike_step(underlying)
    norm = []
    for l in legs:
        norm.append({
            "sign": 1.0 if str(l.get("action", "BUY")).upper() == "BUY" else -1.0,
            "opt": str(l.get("option_type", "CE")).upper(),
            "offset": int(l.get("offset") or 0),
            "qty": int(l.get("qty_lots") or 1),
        })
    trades: list[SimTrade] = []
    idx = 6
    last = len(candles_5m) - 4
    while idx < last:
        features = feature_extractor(candles_5m, idx)
        ctx = {"progress": idx / len(candles_5m), "underlying": underlying}
        if gate(features, idx, ctx).action == "FLAT":
            idx += 1
            continue

        spot_entry = candles_5m[idx][4]
        atm = atm_strike(spot_entry, step)
        T_entry = bs_dte_days / 365
        iv = max(features[10] if len(features) > 10 else 0.15, iv_floor)
        entry_ts = candles_5m[idx][0]

        book = []          # per-leg {strike, opt, sign, qty, entry_prem}
        net_entry = 0.0
        for lg in norm:
            strike = atm + lg["offset"] * step
            prem = pricer(spot_entry, strike, T_entry, lg["opt"], {"iv": iv, "ts": entry_ts})
            book.append({**lg, "strike": strike, "entry_prem": prem})
            net_entry += lg["sign"] * prem * lg["qty"]

        basis = abs(net_entry)
        if basis <= 0.5:            # degenerate (fully offsetting) — skip
            idx += 1
            continue

        status = "TIMEOUT"
        exit_idx = idx
        final_pnl = 0.0
        max_fav = 0.0
        max_adv = 0.0
        for j in range(idx + 1, min(idx + max_hold_bars, len(candles_5m))):
            spot_j = candles_5m[j][4]
            T_j = max(T_entry - (j - idx) * 5 / (60 * 24 * 365), 1 / 365 / 24)
            mtm = 0.0
            for b in book:
                pj = pricer(spot_j, b["strike"], T_j, b["opt"], {"iv": iv, "ts": candles_5m[j][0]})
                mtm += b["sign"] * pj * b["qty"]
            pnl = mtm - net_entry               # rupee P&L per (share × lot fold)
            pnl_pct_now = pnl / basis * 100
            if pnl_pct_now > max_fav: max_fav = pnl_pct_now
            if pnl_pct_now < max_adv: max_adv = pnl_pct_now
            exit_idx = j
            final_pnl = pnl
            if pnl >= target_pct * basis:
                status = "TP"; break
            if pnl <= -stop_pct * basis:
                status = "SL"; break

        pnl_pct = final_pnl / basis * 100
        reward = reward_for(status, pnl_pct, target_pct, stop_pct)
        struct = "+".join(f"{'+' if b['sign']>0 else '-'}{b['opt']}@{int(b['strike'])}" for b in book)
        trade = SimTrade(
            entry_idx=idx, exit_idx=exit_idx,
            # Fold the net basis so compute_roi's (exit-entry)*lot*qty == P&L.
            entry_prem=basis, exit_prem=basis + final_pnl,
            strike=book[0]["strike"], option_type="SPREAD",
            action="LONG" if net_entry > 0 else "SHORT", status=status,
            pnl_pct=pnl_pct, reward=reward, qty_lots=1,
            entry_signal={"structure": struct,
                          "net_entry_prem": round(net_entry, 2),
                          "legs": [{"action": "BUY" if b["sign"] > 0 else "SELL",
                                    "option_type": b["opt"], "strike": b["strike"],
                                    "qty_lots": b["qty"], "entry_prem": round(b["entry_prem"], 2)}
                                   for b in book]},
            mae_pct=round(max_adv, 3), mfe_pct=round(max_fav, 3),
            iv_used=iv,
        )
        trades.append(trade)
        idx = exit_idx + 1
    return trades


# ── Capital-sequenced ROI w/ realistic friction ────────────────────
def compute_roi(
    trades: list[SimTrade] | list[dict],
    *,
    starting_capital: float = 100_000.0,
    lot_size: int = 65,
    brokerage_per_trade: float = 40.0,     # ₹20/leg × 2 legs (Zerodha/Upstox)
    slippage_pct: float = 0.003,           # 0.3% round-trip spread cross
    stt_sell_pct: float = 0.000625,        # 0.0625% of premium × lot, sell side
    exchange_pct: float = 0.00053,         # 0.053% × premium × lot × both legs
    gst_pct: float = 0.18,                 # GST on (brokerage + exchange)
) -> dict:
    """Sequence trades through a capital account.

    Friction breakdown per trade (closes NU-12b):
      brokerage    = `brokerage_per_trade`
      slippage     = entry_prem * lot * slippage_pct
      STT          = exit_prem  * lot * stt_sell_pct  (sell side only)
      exchange     = (entry_prem + exit_prem) * lot * exchange_pct
      taxes        = (brokerage + exchange) * gst_pct
      total        = sum of above
    """
    capital = starting_capital
    peak = starting_capital
    max_dd = 0.0
    taken = skipped = wins = 0
    pnl_inr = 0.0
    fees_total = 0.0
    equity = [capital]

    def _as(t):
        if isinstance(t, SimTrade):
            return {
                "entry_prem": t.entry_prem, "exit_prem": t.exit_prem,
                "qty_lots": t.qty_lots,
            }
        return t

    for t in trades:
        tt = _as(t)
        lots = tt.get("qty_lots") or 1
        qty = lot_size * lots
        outlay = tt["entry_prem"] * qty

        if outlay > capital:
            skipped += 1
            continue

        # Friction
        slippage = tt["entry_prem"] * qty * slippage_pct
        stt = tt["exit_prem"] * qty * stt_sell_pct
        exch = (tt["entry_prem"] + tt["exit_prem"]) * qty * exchange_pct
        taxes = (brokerage_per_trade + exch) * gst_pct
        friction = brokerage_per_trade + slippage + stt + exch + taxes

        gross = (tt["exit_prem"] - tt["entry_prem"]) * qty
        net = gross - friction
        capital += net
        pnl_inr += net
        fees_total += friction
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
        "fees_inr_total": round(fees_total, 2),
        "fees_inr_per_trade": round(fees_total / taken, 2) if taken else 0.0,
        "friction_model": {
            "brokerage_per_trade": brokerage_per_trade,
            "slippage_pct": slippage_pct,
            "stt_sell_pct": stt_sell_pct,
            "exchange_pct": exchange_pct,
            "gst_pct": gst_pct,
        },
    }
