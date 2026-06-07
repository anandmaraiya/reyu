"""EOD Bhavcopy backtest harness — admin-flavored, used to validate
the RL bandit's BS-synthetic numbers against real option pricing."""
from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Query

from app.sim.eod_engine import (
    simulate_eod, trades_to_roi_dicts, EodDecision,
)
from app.sim.engine import compute_roi

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
