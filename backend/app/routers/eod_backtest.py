"""EOD Bhavcopy backtest harness — admin-flavored, used to validate
the RL bandit's BS-synthetic numbers against real option pricing."""
from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Query

from app.sim.eod_engine import (
    simulate_eod, trades_to_roi_dicts, EodDecision,
)
from app.sim.engine import compute_roi
from app.sim.eod_bandit import train_test_eod_bandit
from app.sim.iron_condor_eod_bandit import train_test_iron_condor_bandit
from app.sim.iron_condor_intraday import replay_window as ic_intraday_replay
from app.sim.regime_router_eod import regime_router_backtest

router = APIRouter()


# ── Built-in deciders ──────────────────────────────────────────────
def _decider_always_long(d, atm, hist):
    return EodDecision(action="LONG")


def _decider_always_short(d, atm, hist):
    return EodDecision(action="SHORT")


def _decider_momentum(d, atm, hist):
    """Simple: if yesterday's ATM rose, go LONG; if fell, go SHORT."""
    if len(hist) < 2:
        return EodDecision(action="FLAT")
    if hist[-1].get("atm") and hist[-2].get("atm"):
        if hist[-1]["atm"] > hist[-2]["atm"]:
            return EodDecision(action="LONG", metadata={"reason": "atm-rising"})
        if hist[-1]["atm"] < hist[-2]["atm"]:
            return EodDecision(action="SHORT", metadata={"reason": "atm-falling"})
    return EodDecision(action="FLAT")


def _decider_mean_reversion(d, atm, hist):
    """Opposite of momentum — buy puts when ATM rising."""
    if len(hist) < 2:
        return EodDecision(action="FLAT")
    if hist[-1].get("atm") and hist[-2].get("atm"):
        if hist[-1]["atm"] > hist[-2]["atm"]:
            return EodDecision(action="SHORT", metadata={"reason": "fade-up"})
        if hist[-1]["atm"] < hist[-2]["atm"]:
            return EodDecision(action="LONG", metadata={"reason": "fade-down"})
    return EodDecision(action="FLAT")


_DECIDERS = {
    "always_long": _decider_always_long,
    "always_short": _decider_always_short,
    "momentum": _decider_momentum,
    "mean_reversion": _decider_mean_reversion,
}


# ── Endpoint ───────────────────────────────────────────────────────
@router.post("/bandit-train-test")
async def bandit_train_test(
    underlying: str = Query("NSE:NIFTY50-INDEX"),
    train_start: date = Query(...),
    train_end: date = Query(...),
    test_start: date = Query(...),
    test_end: date = Query(...),
    target_pct: float = Query(0.25, gt=0, lt=2),
    stop_pct: float = Query(0.15, gt=0, lt=2),
    max_hold_days: int = Query(5, ge=1, le=30),
    only_dte_le: int = Query(14, ge=1, le=60),
    epsilon: float = Query(0.10, ge=0, le=0.5),
    lr: float = Query(0.10, gt=0, lt=1),
    epochs: int = Query(1, ge=1, le=20),
    min_conviction: float = Query(0.0, ge=0.0, le=0.9),
    starting_capital: float = Query(100_000, ge=10_000),
    lot_size: int = Query(65, ge=1),
    seed: int | None = Query(None),
    persist: bool = Query(False),
):
    """Train an EOD contextual bandit on Bhavcopy data, then evaluate
    read-only on the holdout. Returns metrics + fitted weights.

    When `persist=true`, the fitted policy is upserted into `rl_policy`
    for this underlying — i.e. live RL_BANDIT strategies pick it up on
    next reload."""
    return await train_test_eod_bandit(
        underlying,
        train_start=train_start, train_end=train_end,
        test_start=test_start, test_end=test_end,
        target_pct=target_pct, stop_pct=stop_pct,
        max_hold_days=max_hold_days, only_dte_le=only_dte_le,
        epsilon=epsilon, lr=lr, epochs=epochs,
        min_conviction=min_conviction,
        starting_capital=starting_capital, lot_size=lot_size,
        seed=seed, persist=persist,
    )


@router.post("/iron-condor-train-test")
async def iron_condor_train_test(
    underlying: str = Query("NSE:NIFTY50-INDEX"),
    train_start: date = Query(...),
    train_end: date = Query(...),
    test_start: date = Query(...),
    test_end: date = Query(...),
    short_strike_offset: int = Query(50, ge=1, le=2000),
    long_strike_offset: int = Query(400, ge=50, le=5000),
    only_dte_le: int = Query(14, ge=1, le=60),
    epsilon: float = Query(0.10, ge=0, le=0.5),
    lr: float = Query(0.10, gt=0, lt=1),
    epochs: int = Query(1, ge=1, le=20),
    min_conviction: float = Query(0.05, ge=0.0, le=0.9),
    starting_capital: float = Query(100_000, ge=10_000),
    lot_size: int = Query(65, ge=1),
    seed: int | None = Query(None),
    persist: bool = Query(False),
):
    """Train an iron-condor (intraday, EOD-square-off) bandit on Bhavcopy.

    Structure per entry:
        SELL ATM±short_strike_offset CE/PE   (1:1 lots)
        BUY  ATM±long_strike_offset  CE/PE   (1:1 lots)
    Open at day open, close at day close (no overnight).

    When `persist=true` the policy is upserted to rl_policy keyed by
    `{underlying}/IC` (suffix avoids collision with single-leg bandit)."""
    return await train_test_iron_condor_bandit(
        underlying,
        train_start=train_start, train_end=train_end,
        test_start=test_start, test_end=test_end,
        short_strike_offset=short_strike_offset,
        long_strike_offset=long_strike_offset,
        only_dte_le=only_dte_le,
        epsilon=epsilon, lr=lr, epochs=epochs,
        min_conviction=min_conviction,
        starting_capital=starting_capital, lot_size=lot_size,
        seed=seed, persist=persist,
    )


@router.post("/iron-condor-intraday-replay")
async def iron_condor_intraday_replay(
    underlying: str = Query("NSE:NIFTY50-INDEX"),
    start_date: date = Query(...),
    end_date: date = Query(...),
    entry_time_ist: str = Query("09:30"),
    eod_close_time_ist: str = Query("15:20"),
    short_strike_offset: int = Query(50, ge=1, le=2000),
    long_strike_offset: int = Query(400, ge=50, le=5000),
    stop_credit_multiple: float | None = Query(1.0, ge=0.1, le=10.0),
    starting_capital: float = Query(100_000, ge=10_000),
    lot_size: int = Query(65, ge=1),
):
    """Replay every trading day in window using real intraday 1-min
    `option_strike_snapshot` data. Applies MTM stop. Compare with
    `stop_credit_multiple=null` (or large) to see the same window with
    no stop — quantifies the value of intraday risk management.

    NOTE: only covers dates within the forward-collected snapshot
    window (recent ~weeks). For multi-year backtest, see the
    Bhavcopy-based train-test endpoint."""
    from datetime import time as _t
    ent = _t.fromisoformat(entry_time_ist)
    eod = _t.fromisoformat(eod_close_time_ist)
    return await ic_intraday_replay(
        underlying, start_date, end_date,
        entry_time_ist=ent, eod_close_time_ist=eod,
        short_strike_offset=short_strike_offset,
        long_strike_offset=long_strike_offset,
        stop_credit_multiple=stop_credit_multiple,
        starting_capital=starting_capital, lot_size=lot_size,
    )


@router.post("/regime-router")
async def regime_router(
    underlying: str = Query("NSE:NIFTY50-INDEX"),
    start_date: date = Query(...),
    end_date: date = Query(...),
    only_dte_le: int = Query(14, ge=1, le=60),
    momentum_lookback: int = Query(3, ge=1, le=20),
    trend_threshold_pct: float = Query(1.0, ge=0.1, le=10.0),
    range_threshold_pct: float = Query(0.5, ge=0.0, le=5.0),
    pcr_low: float = Query(0.7, ge=0.1, le=3.0),
    pcr_high: float = Query(1.4, ge=0.1, le=5.0),
    short_strike_offset: int = Query(50, ge=1, le=2000),
    long_strike_offset: int = Query(400, ge=50, le=5000),
    starting_capital: float = Query(100_000, ge=10_000),
    lot_size: int = Query(65, ge=1),
):
    """Regime-aware backtest: route each day to LONG_CE (trend up),
    LONG_PE (trend down), IRON_CONDOR (sideways), or FLAT, based on
    rolling momentum + PCR. EOD square-off on all trades.

    Compares the router against always_condor and always_long_ce
    baselines over the same window."""
    return await regime_router_backtest(
        underlying,
        start_date=start_date, end_date=end_date,
        only_dte_le=only_dte_le,
        momentum_lookback=momentum_lookback,
        trend_threshold_pct=trend_threshold_pct,
        range_threshold_pct=range_threshold_pct,
        pcr_band=(pcr_low, pcr_high),
        short_strike_offset=short_strike_offset,
        long_strike_offset=long_strike_offset,
        starting_capital=starting_capital, lot_size=lot_size,
    )


@router.post("/eod")
async def run_eod_backtest(
    underlying: str = Query("NSE:NIFTY50-INDEX"),
    decider: str = Query("momentum", regex="^(always_long|always_short|momentum|mean_reversion)$"),
    start_date: date = Query(...),
    end_date: date = Query(...),
    target_pct: float = Query(0.25, gt=0, lt=2),
    stop_pct: float = Query(0.15, gt=0, lt=2),
    max_hold_days: int = Query(5, ge=1, le=30),
    only_if_dte_le: int = Query(14, ge=1, le=60),
    starting_capital: float = Query(100_000),
    lot_size: int = Query(65, ge=1),
    realistic_friction: bool = Query(True),
):
    """Run an EOD Bhavcopy-backed backtest. `decider` picks the rule."""
    decide_fn = _DECIDERS[decider]
    trades = await simulate_eod(
        underlying,
        decide_fn,
        start_date=start_date, end_date=end_date,
        target_pct=target_pct, stop_pct=stop_pct,
        max_hold_days=max_hold_days, only_if_dte_le=only_if_dte_le,
    )
    n = len(trades)
    wins = sum(1 for t in trades if t.status == "TP")
    losses = sum(1 for t in trades if t.status == "SL")
    timeouts = n - wins - losses
    pnl_pcts = [t.pnl_pct for t in trades]
    avg_pnl = round(sum(pnl_pcts) / n, 2) if n else None

    roi_input = trades_to_roi_dicts(trades)
    roi_kwargs = {"starting_capital": starting_capital, "lot_size": lot_size}
    if not realistic_friction:
        roi_kwargs.update({
            "brokerage_per_trade": 50.0,
            "slippage_pct": 0, "stt_sell_pct": 0,
            "exchange_pct": 0, "gst_pct": 0,
        })
    roi = compute_roi(roi_input, **roi_kwargs)

    return {
        "underlying": underlying,
        "decider": decider,
        "window": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "brackets": {"tp_pct": target_pct, "sl_pct": stop_pct,
                     "max_hold_days": max_hold_days, "only_if_dte_le": only_if_dte_le},
        "trade_summary": {
            "total": n, "wins": wins, "losses": losses, "timeouts": timeouts,
            "win_rate": round(wins / n, 3) if n else None,
            "avg_pnl_per_trade_pct": avg_pnl,
        },
        "roi": roi,
        "first_trade": {
            "entry_date": trades[0].entry_date.isoformat() if trades else None,
            "exit_date": trades[0].exit_date.isoformat() if trades else None,
            "strike": trades[0].strike if trades else None,
            "option_type": trades[0].option_type if trades else None,
            "entry_prem": trades[0].entry_prem if trades else None,
            "exit_prem": trades[0].exit_prem if trades else None,
            "status": trades[0].status if trades else None,
        } if trades else None,
    }
