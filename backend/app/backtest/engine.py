"""Backtesting engine over stored snapshot + tick history.

Two strategies supported out of the box (extensible via the `STRATS` dict):

  follow_bias    Each new trading day at open, read the chain's bias score.
                 If bullish → buy ATM CE; if bearish → buy ATM PE; flat
                 otherwise. Mark-to-market intraday via Black-Scholes
                 (synthetic ATM IV from atm_iv snapshot), exit at close.

  pcr_meanrev   Fade extreme PCR readings: if PCR > 1.3 → buy ATM CE
                 (calls oversold); if PCR < 0.7 → buy ATM PE (puts
                 oversold). Same intraday MTM exit.

For each trading session in the requested window we replay the stored
`option_snapshot` rows for the underlying, pick a single ATM strike at
entry, value it through the day, and book the realised P&L at close.

Metrics returned:
  cum_pnl, max_drawdown, win_rate, sharpe (daily-bar based, annualised),
  avg_win, avg_loss, total_trades.

This is an MVP — it values options via Black-Scholes from spot + ATM IV
(no per-strike IV surface), which is good enough for directional /
mean-reversion bias-based strategies but understates skew effects for
spreads. Real skew-aware backtesting needs per-strike snapshot history,
which is a follow-up scheduler change.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import OptionSnapshot
from app.analytics.greeks import bs_price

IST = timezone(timedelta(hours=5, minutes=30))
RISK_FREE = 0.07


# ── Strategy signal functions ─────────────────────────────────
# Each strategy is `(snap_at_open) -> Optional["CE" | "PE"]`

def _follow_bias(open_snap: OptionSnapshot) -> str | None:
    if open_snap.bias_score is None:
        return None
    if open_snap.bias_score >= 1:
        return "CE"
    if open_snap.bias_score <= -1:
        return "PE"
    return None


def _pcr_meanrev(open_snap: OptionSnapshot) -> str | None:
    pcr = open_snap.pcr_oi or 0
    if pcr > 1.3:
        return "CE"
    if pcr < 0.7:
        return "PE"
    return None


STRATS: dict[str, Callable[[OptionSnapshot], str | None]] = {
    "follow_bias": _follow_bias,
    "pcr_meanrev": _pcr_meanrev,
}


# ── Backtest core ─────────────────────────────────────────────
@dataclass
class Trade:
    day: str            # YYYY-MM-DD
    side: str           # CE | PE
    strike: float
    entry_spot: float
    entry_premium: float
    exit_spot: float
    exit_premium: float
    pnl_per_unit: float
    return_pct: float


def _group_by_day(rows: list[OptionSnapshot]) -> dict[str, list[OptionSnapshot]]:
    by_day: dict[str, list[OptionSnapshot]] = {}
    for r in rows:
        ist = r.ts.replace(tzinfo=timezone.utc).astimezone(IST)
        d = ist.strftime("%Y-%m-%d")
        by_day.setdefault(d, []).append(r)
    for d in by_day:
        by_day[d].sort(key=lambda r: r.ts)
    return by_day


def _years_to_expiry(open_ts: datetime, expiry: datetime) -> float:
    secs = (expiry - open_ts).total_seconds()
    return max(secs / (365 * 24 * 3600), 0.5 / 365)


async def run_backtest(
    s: AsyncSession,
    symbol: str,
    strategy: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    if strategy not in STRATS:
        return {"error": f"Unknown strategy: {strategy}. Available: {', '.join(STRATS)}"}
    signal_fn = STRATS[strategy]

    q = (
        select(OptionSnapshot)
        .where(OptionSnapshot.symbol == symbol,
               OptionSnapshot.ts >= start, OptionSnapshot.ts <= end)
        .order_by(OptionSnapshot.ts)
    )
    rows = (await s.execute(q)).scalars().all()
    if not rows:
        return {"trades": [], "metrics": {}, "equity_curve": [],
                "error": "No snapshot history in this window — track this symbol for at least one session."}

    by_day = _group_by_day(rows)
    trades: list[Trade] = []
    equity_curve: list[dict] = []
    cum_pnl = 0.0

    for d, day_rows in sorted(by_day.items()):
        if len(day_rows) < 2:
            continue
        open_snap = day_rows[0]
        close_snap = day_rows[-1]
        signal = signal_fn(open_snap)
        if signal is None:
            equity_curve.append({"day": d, "cum_pnl": round(cum_pnl, 2), "trade": None})
            continue

        strike = open_snap.atm_strike or 0
        if not strike:
            equity_curve.append({"day": d, "cum_pnl": round(cum_pnl, 2), "trade": None})
            continue

        # Black-Scholes synthetic entry / exit
        iv = open_snap.atm_iv or 0.20
        T_open = _years_to_expiry(open_snap.ts, open_snap.expiry)
        T_close = _years_to_expiry(close_snap.ts, close_snap.expiry)
        entry_prem = bs_price(open_snap.ltp, strike, T_open, RISK_FREE, iv, signal)
        exit_iv = close_snap.atm_iv or iv
        exit_prem = bs_price(close_snap.ltp, strike, T_close, RISK_FREE, exit_iv, signal)
        pnl_unit = exit_prem - entry_prem
        ret_pct = (pnl_unit / entry_prem * 100) if entry_prem > 0 else 0.0

        trades.append(Trade(
            day=d, side=signal, strike=strike,
            entry_spot=open_snap.ltp, entry_premium=round(entry_prem, 2),
            exit_spot=close_snap.ltp, exit_premium=round(exit_prem, 2),
            pnl_per_unit=round(pnl_unit, 2),
            return_pct=round(ret_pct, 2),
        ))
        cum_pnl += pnl_unit
        equity_curve.append({"day": d, "cum_pnl": round(cum_pnl, 2),
                             "trade": {"side": signal, "pnl": round(pnl_unit, 2)}})

    # ── Metrics ───────────────────────────────────────────────
    pnl_series = [t.pnl_per_unit for t in trades]
    metrics: dict[str, Any] = {
        "total_trades": len(trades),
        "cum_pnl": round(sum(pnl_series), 2),
        "win_rate": round(sum(1 for p in pnl_series if p > 0) / max(len(pnl_series), 1), 3),
        "avg_win": round(sum(p for p in pnl_series if p > 0) / max(sum(1 for p in pnl_series if p > 0), 1), 2),
        "avg_loss": round(sum(p for p in pnl_series if p < 0) / max(sum(1 for p in pnl_series if p < 0), 1), 2),
    }
    if len(pnl_series) >= 2:
        mean = sum(pnl_series) / len(pnl_series)
        var = sum((p - mean) ** 2 for p in pnl_series) / (len(pnl_series) - 1)
        sd = math.sqrt(var)
        metrics["sharpe_annualised"] = round((mean / sd) * math.sqrt(252), 2) if sd > 0 else None
    # Max drawdown across equity curve
    peak = 0.0; max_dd = 0.0
    for pt in equity_curve:
        peak = max(peak, pt["cum_pnl"])
        max_dd = min(max_dd, pt["cum_pnl"] - peak)
    metrics["max_drawdown"] = round(max_dd, 2)

    return {
        "symbol": symbol, "strategy": strategy,
        "from": start.isoformat(), "to": end.isoformat(),
        "trades": [t.__dict__ for t in trades],
        "equity_curve": equity_curve,
        "metrics": metrics,
    }


def list_strategies() -> list[dict]:
    return [
        {"id": "follow_bias", "name": "Follow Bias",
         "description": "Buy ATM CE when bias score ≥ 1, ATM PE when ≤ -1, flat otherwise. Exit at session close."},
        {"id": "pcr_meanrev", "name": "PCR Mean-Reversion",
         "description": "Buy ATM CE when PCR > 1.3 (puts oversold), ATM PE when PCR < 0.7. Exit at close."},
    ]
