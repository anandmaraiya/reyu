"""Regime-aware EOD strategy router on Bhavcopy.

Classifies each trading day into one of four regimes based on rolling
ATM momentum and PCR, then routes to the regime's best instrument:

    TREND_UP   (mom_3d > +trend_th)  → BUY ATM CE   (long call, EOD square-off)
    TREND_DOWN (mom_3d < -trend_th)  → BUY ATM PE   (long put,  EOD square-off)
    SIDEWAYS   (|mom_3d| < range_th  → IRON CONDOR  (4-leg credit, EOD square-off)
                AND pcr in band)
    FLAT       (everything else)     → SKIP

All trades open at day open and close at day close — no overnight risk,
matching the user's "stop strictly at end of day" requirement.

For comparison the backtest reports the router alongside two baselines:
"always_condor" and "always_long_ce" run over the same days.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, OptionEod
from app.sim.engine import compute_roi

log = logging.getLogger("reyu.sim.regime_router")


@dataclass
class DayBar:
    trade_date: date
    expiry: datetime
    atm_strike: float
    pcr_oi: float
    dte: int
    by_strike: dict


async def _load_window(s: AsyncSession, underlying: str,
                       start: date, end: date) -> list[OptionEod]:
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


def _find_atm(by_strike: dict) -> tuple[float | None, object, object]:
    cands = []
    for k, pair in by_strike.items():
        ce, pe = pair.get("CE"), pair.get("PE")
        if ce and pe and ce.close > 0 and pe.close > 0:
            cands.append((k, abs(ce.close - pe.close), ce, pe))
    if not cands:
        return None, None, None
    k, _, ce, pe = min(cands, key=lambda x: x[1])
    return k, ce, pe


def _build_bars(idx: dict, only_dte_le: int = 14) -> list[DayBar]:
    bars: list[DayBar] = []
    for d in sorted(idx.keys()):
        expiries = sorted([ex for ex in idx[d].keys() if ex.date() >= d])
        for ex in expiries:
            atm, _ce, _pe = _find_atm(idx[d][ex])
            if atm is None:
                continue
            dte = (ex.date() - d).days
            if dte > only_dte_le or dte < 1:
                continue
            ce_oi = sum(p["CE"].oi for p in idx[d][ex].values() if "CE" in p) or 1
            pe_oi = sum(p["PE"].oi for p in idx[d][ex].values() if "PE" in p) or 1
            pcr = pe_oi / ce_oi
            bars.append(DayBar(
                trade_date=d, expiry=ex, atm_strike=atm,
                pcr_oi=pcr, dte=dte, by_strike=idx[d][ex],
            ))
            break
    return bars


# ── Regime classifier ──────────────────────────────────────────────
def _classify_regime(
    bar: DayBar,
    bars_history: list[DayBar],
    *,
    momentum_lookback: int = 3,
    trend_threshold_pct: float = 1.0,
    range_threshold_pct: float = 0.5,
    pcr_band: tuple[float, float] = (0.7, 1.4),
) -> tuple[str, float]:
    """Returns (regime_label, mom_3d_pct)."""
    if len(bars_history) < momentum_lookback:
        return "FLAT", 0.0
    ref = bars_history[-momentum_lookback]
    if not ref.atm_strike:
        return "FLAT", 0.0
    mom_pct = (bar.atm_strike / ref.atm_strike - 1.0) * 100

    if mom_pct >= trend_threshold_pct:
        return "TREND_UP", mom_pct
    if mom_pct <= -trend_threshold_pct:
        return "TREND_DOWN", mom_pct
    if abs(mom_pct) <= range_threshold_pct and pcr_band[0] <= bar.pcr_oi <= pcr_band[1]:
        return "SIDEWAYS", mom_pct
    return "FLAT", mom_pct


# ── Per-regime trade simulators (open → close, EOD square-off) ─────
# All sims take an explicit `traded_strike` (= yesterday's close-ATM) to
# avoid same-day look-ahead. The first day of the window has no prior
# bar — caller skips it.
def _trade_long_ce(bar: DayBar, traded_strike: float) -> dict | None:
    atm_pair = bar.by_strike.get(traded_strike, {})
    ce = atm_pair.get("CE")
    if not ce or ce.open <= 1 or ce.close <= 0:
        return None
    pnl = ce.close - ce.open
    return {
        "date": bar.trade_date.isoformat(), "regime": "TREND_UP",
        "action": "LONG_CE", "strike": traded_strike,
        "entry_prem": ce.open, "exit_prem": ce.close,
        "status": "TP" if pnl > 0 else "SL",
        "pnl_pct": (pnl / ce.open) * 100, "qty_lots": 1,
    }


def _trade_long_pe(bar: DayBar, traded_strike: float) -> dict | None:
    atm_pair = bar.by_strike.get(traded_strike, {})
    pe = atm_pair.get("PE")
    if not pe or pe.open <= 1 or pe.close <= 0:
        return None
    pnl = pe.close - pe.open
    return {
        "date": bar.trade_date.isoformat(), "regime": "TREND_DOWN",
        "action": "LONG_PE", "strike": traded_strike,
        "entry_prem": pe.open, "exit_prem": pe.close,
        "status": "TP" if pnl > 0 else "SL",
        "pnl_pct": (pnl / pe.open) * 100, "qty_lots": 1,
    }


def _trade_iron_condor(
    bar: DayBar,
    traded_atm: float,
    short_strike_offset: int = 50,
    long_strike_offset: int = 400,
) -> dict | None:
    sc = bar.by_strike.get(traded_atm + short_strike_offset, {}).get("CE")
    sp = bar.by_strike.get(traded_atm - short_strike_offset, {}).get("PE")
    lc = bar.by_strike.get(traded_atm + long_strike_offset, {}).get("CE")
    lp = bar.by_strike.get(traded_atm - long_strike_offset, {}).get("PE")
    if not all([sc, sp, lc, lp]):
        return None
    if any(l.open <= 0.05 for l in [sc, sp, lc, lp]):
        return None
    entry_credit = (sc.open + sp.open) - (lc.open + lp.open)
    if entry_credit <= 0:
        return None
    exit_debit = (sc.close + sp.close) - (lc.close + lp.close)
    pnl = entry_credit - exit_debit
    return {
        "date": bar.trade_date.isoformat(), "regime": "SIDEWAYS",
        "action": "IRON_CONDOR", "strike": traded_atm,
        "entry_prem": entry_credit, "exit_prem": exit_debit,
        "status": "TP" if pnl > 0 else "SL",
        "pnl_pct": (pnl / entry_credit) * 100, "qty_lots": 1,
    }


# ── Top-level backtest ────────────────────────────────────────────
async def regime_router_backtest(
    underlying: str,
    *,
    start_date: date, end_date: date,
    only_dte_le: int = 14,
    momentum_lookback: int = 3,
    trend_threshold_pct: float = 1.0,
    range_threshold_pct: float = 0.5,
    pcr_band: tuple[float, float] = (0.7, 1.4),
    short_strike_offset: int = 50,
    long_strike_offset: int = 400,
    starting_capital: float = 100_000,
    lot_size: int = 65,
) -> dict:
    async with SessionLocal() as s:
        rows = await _load_window(s, underlying, start_date, end_date)
    idx = _index_by_day(rows)
    bars = _build_bars(idx, only_dte_le=only_dte_le)
    log.info("regime_router: %d bars %s..%s", len(bars), start_date, end_date)

    router_trades: list[dict] = []
    always_condor_trades: list[dict] = []
    always_long_trades: list[dict] = []
    regime_counts: dict[str, int] = defaultdict(int)
    regime_pnl: dict[str, list[float]] = defaultdict(list)

    history: list[DayBar] = []
    skipped_first_day = 0
    for bar in bars:
        # router decision (history excludes today, so classifier is pure no-lookahead)
        regime, mom = _classify_regime(
            bar, history,
            momentum_lookback=momentum_lookback,
            trend_threshold_pct=trend_threshold_pct,
            range_threshold_pct=range_threshold_pct,
            pcr_band=pcr_band,
        )
        regime_counts[regime] += 1

        # Trade strike = YESTERDAY's close-ATM, not today's. This is the
        # actual strike we'd buy/sell at today's open in a live system:
        # the chain we see when entering the order is yesterday's close.
        # Without this, the previous backtest leaked today's outcome into
        # strike selection (close-ATM is itself a function of intraday
        # move) and inflated win-rate while distorting absolute pnl%.
        if not history:
            skipped_first_day += 1
            history.append(bar)
            continue
        traded_strike = history[-1].atm_strike
        history.append(bar)

        if regime == "TREND_UP":
            t = _trade_long_ce(bar, traded_strike)
        elif regime == "TREND_DOWN":
            t = _trade_long_pe(bar, traded_strike)
        elif regime == "SIDEWAYS":
            t = _trade_iron_condor(bar, traded_strike, short_strike_offset, long_strike_offset)
        else:
            t = None
        if t:
            t["mom_3d_pct"] = round(mom, 2)
            router_trades.append(t)
            regime_pnl[regime].append(t["pnl_pct"])

        # baselines (also no-lookahead: same yesterday's-ATM rule)
        c = _trade_iron_condor(bar, traded_strike, short_strike_offset, long_strike_offset)
        if c:
            always_condor_trades.append(c)
        l = _trade_long_ce(bar, traded_strike)
        if l:
            always_long_trades.append(l)

    router_roi = compute_roi(router_trades, starting_capital=starting_capital, lot_size=lot_size)
    condor_roi = compute_roi(always_condor_trades, starting_capital=starting_capital, lot_size=lot_size)
    long_roi = compute_roi(always_long_trades, starting_capital=starting_capital, lot_size=lot_size)

    def _wr(trades): return round(
        sum(1 for t in trades if t["status"] == "TP") / max(1, len(trades)), 3
    )

    per_regime_summary = {
        r: {
            "days": regime_counts[r],
            "trades_executed": sum(1 for t in router_trades if t["regime"] == r),
            "win_rate": _wr([t for t in router_trades if t["regime"] == r]),
            "avg_pnl_pct": round(
                sum(t["pnl_pct"] for t in router_trades if t["regime"] == r)
                / max(1, sum(1 for t in router_trades if t["regime"] == r)), 2
            ),
        }
        for r in ("TREND_UP", "TREND_DOWN", "SIDEWAYS", "FLAT")
    }

    return {
        "underlying": underlying,
        "window": [start_date.isoformat(), end_date.isoformat()],
        "params": {
            "momentum_lookback": momentum_lookback,
            "trend_threshold_pct": trend_threshold_pct,
            "range_threshold_pct": range_threshold_pct,
            "pcr_band": list(pcr_band),
            "condor_short_otm_offset": short_strike_offset,
            "condor_long_otm_offset": long_strike_offset,
        },
        "total_bars": len(bars),
        "regime_distribution": dict(regime_counts),
        "per_regime": per_regime_summary,
        "router": {
            "trades": len(router_trades),
            "win_rate": _wr(router_trades),
            "roi_pct": router_roi.get("roi_pct"),
            "max_drawdown_pct": router_roi.get("max_drawdown_pct"),
            "final_capital": router_roi.get("final_capital"),
        },
        "baseline_always_condor": {
            "trades": len(always_condor_trades),
            "win_rate": _wr(always_condor_trades),
            "roi_pct": condor_roi.get("roi_pct"),
            "max_drawdown_pct": condor_roi.get("max_drawdown_pct"),
            "final_capital": condor_roi.get("final_capital"),
        },
        "baseline_always_long_ce": {
            "trades": len(always_long_trades),
            "win_rate": _wr(always_long_trades),
            "roi_pct": long_roi.get("roi_pct"),
            "max_drawdown_pct": long_roi.get("max_drawdown_pct"),
            "final_capital": long_roi.get("final_capital"),
        },
    }
