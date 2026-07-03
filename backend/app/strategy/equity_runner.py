"""EQUITY_EOD backtest runner — daily-bar cash-equity simulation.

Dispatched from app.strategy.runner when spec.kind == "EQUITY_EOD".
Deliberately separate from the intraday options simulator
(app.sim.engine) — the mechanics differ everywhere: daily bars instead
of 5-min, delivery friction instead of option premiums, multi-day holds
instead of forced EOD square-off.

Semantics (no lookahead):
  * Conditions are evaluated on day i's CLOSE using eq_* features
    (app.strategy.equity_features) computed from candles[0..i].
  * A passing signal enters at day i+1's OPEN.
  * SCHEDULE trigger enters on every day whose weekday matches
    schedule.days (systematic accumulation / SIP-style), subject to
    risk.max_concurrent open positions.
  * Exits, checked each day after entry, in order:
      1. SL   — day's low breaches entry*(1-sl_pct); fills at stop
                (or at open if the day gapped through it).
      2. TP   — day's high reaches entry*(1+tp_pct); fills at target
                (or at open on a gap). Same-day SL+TP resolves to SL
                (conservative).
      3. TRAIL— close drops trailing_sl_pct below the highest close
                since entry; fills at close.
      4. TIME — held >= time_stop_days; fills at close.
      5. EOP  — run period ended; fills at final close.
  * Position size: floor(min(risk.max_position_inr, available capital)
    / entry price) shares; skips (and counts) entries it can't afford.

Friction model (Indian delivery, discount broker):
    brokerage 0 · STT 0.1% both sides · stamp 0.015% buy ·
    exchange 0.00297% both sides · DP ₹16 per sell · GST 18% on charges ·
    slippage 0.05% each side

Outputs the same StrategyTrade rows / metrics keys / equity_curve shape
as the options runner so every existing page (runs, trades, journal,
compare) renders equity results unchanged.
"""
from __future__ import annotations

import json
import logging
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal, Strategy, StrategyRun, StrategyTrade
from app.fyers import client as fy
from app.strategy.conditions import evaluate_one_dict
from app.strategy.equity_features import compute_equity_features, WARMUP_DAYS
from app.strategy.spec import StrategySpec

log = logging.getLogger("reyu.strategy.equity_runner")

# ── Friction (delivery) ─────────────────────────────────────────────
FRICTION = {
    "brokerage_per_trade": 0.0,
    "stt_pct": 0.001,          # 0.1% each side on delivery
    "stamp_buy_pct": 0.00015,
    "exchange_pct": 0.0000297,
    "dp_per_sell": 16.0,
    "gst_pct": 0.18,
    "slippage_pct": 0.0005,    # 0.05% each side
    "model": "equity_delivery_v1",
}


def _friction_inr(entry_px: float, exit_px: float, qty: int) -> float:
    buy_val, sell_val = entry_px * qty, exit_px * qty
    stt = (buy_val + sell_val) * FRICTION["stt_pct"]
    stamp = buy_val * FRICTION["stamp_buy_pct"]
    exch = (buy_val + sell_val) * FRICTION["exchange_pct"]
    slip = (buy_val + sell_val) * FRICTION["slippage_pct"]
    gst = (FRICTION["brokerage_per_trade"] + exch) * FRICTION["gst_pct"]
    return stt + stamp + exch + slip + gst + FRICTION["dp_per_sell"]


def _to_daily(candles: list) -> list[list[float]]:
    """Resample candles of any resolution into daily OHLCV bars.

    app.fyers.cache.get_candles serves from the tick_1m store and returns
    intraday bars regardless of the requested resolution, so the runner
    must aggregate. Bars are grouped by IST calendar date (NSE session);
    already-daily input passes through unchanged (one bar per group).
    Output: [day_open_epoch, open, high, low, close, volume]."""
    IST_OFFSET = 5.5 * 3600
    days: dict[Any, list] = {}
    for c in candles:
        key = datetime.utcfromtimestamp(c[0] + IST_OFFSET).date()
        d = days.get(key)
        if d is None:
            days[key] = [c[0], c[1], c[2], c[3], c[4], c[5] or 0]
        else:
            d[2] = max(d[2], c[2])
            d[3] = min(d[3], c[3])
            d[4] = c[4]
            d[5] += c[5] or 0
    return [days[k] for k in sorted(days)]


@dataclass
class EqTrade:
    entry_idx: int
    entry_unix: int
    entry_px: float
    qty: int
    reason: str
    peak_close: float = 0.0
    # filled at exit
    exit_idx: int = -1
    exit_unix: int = 0
    exit_px: float = 0.0
    status: str = ""            # TP | SL | TRAIL | TIME | EOP
    mae_pct: float = 0.0        # worst adverse excursion (close-basis)
    mfe_pct: float = 0.0        # best favourable excursion
    lowest_low: float = field(default=1e18)
    highest_high: float = 0.0

    @property
    def gross_pnl(self) -> float:
        return (self.exit_px - self.entry_px) * self.qty

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - _friction_inr(self.entry_px, self.exit_px, self.qty)

    @property
    def pnl_pct(self) -> float:
        base = self.entry_px * self.qty
        return (self.net_pnl / base * 100.0) if base else 0.0


async def fetch_daily_candles(
    symbol: str, fetch_from: date, fetch_to: date, min_days: int = 30,
) -> tuple[list[list[float]], str]:
    """Daily OHLCV candles for [fetch_from, fetch_to] → (candles, source).

    Primary: Fyers "D" resolution (years of lookback, chunked at ~360
    days/request). Fallback: resample the tick_1m store — when Fyers auth
    is down (daily token expiry) history() serves ~1 day of mock bars,
    but the forward pipeline often has real recent intraday data.
    Raises when neither source yields `min_days`. Shared by the backtest
    runner and the paper-live daily loop."""
    raw_candles: list = []
    chunk_start = fetch_from
    while chunk_start <= fetch_to:
        chunk_end = min(chunk_start + timedelta(days=360), fetch_to)
        try:
            hist = await fy.history(symbol, "D",
                                    chunk_start.isoformat(), chunk_end.isoformat())
            raw_candles.extend(hist.get("candles") or [])
        except Exception as e:
            log.warning("daily history %s %s..%s failed: %s",
                        symbol, chunk_start, chunk_end, e)
        chunk_start = chunk_end + timedelta(days=1)
    # Dedupe on timestamp (chunk boundaries can overlap) + sort
    raw_candles = list({int(c[0]): c for c in raw_candles}.values())
    raw_candles.sort(key=lambda c: c[0])
    source = "FYERS_DAILY"
    candles = _to_daily(raw_candles)

    if len(candles) < min_days:
        from app.fyers import cache as _cache
        cached = await _cache.get_candles(
            symbol, resolution="D",
            range_from=fetch_from.isoformat(), range_to=fetch_to.isoformat(),
        )
        fallback = _to_daily(cached.get("candles") or [])
        if len(fallback) > len(candles):
            candles, source = fallback, "TICK1M_RESAMPLED_DAILY"

    if len(candles) < min_days:
        raise ValueError(f"insufficient daily history for {symbol} "
                         f"({len(candles)} days) — broker auth may be down, "
                         "or the symbol is wrong")
    return candles, source


async def execute_equity_run_inner(run_id: str) -> None:
    """Full EQUITY_EOD backtest for an existing RUNNING StrategyRun row.
    Mirrors runner._execute_run_inner's persistence contract."""
    async with SessionLocal() as s:
        run = (await s.execute(
            select(StrategyRun).where(StrategyRun.id == run_id)
        )).scalar_one_or_none()
        if not run:
            raise ValueError("run not found")

    spec = StrategySpec.model_validate(json.loads(run.config_snapshot))
    params = json.loads(run.params or "{}")
    symbol = spec.universe[0]
    period_start = date.fromisoformat(params["period_start"])
    period_end = date.fromisoformat(params["period_end"])
    capital = float(params.get("starting_capital") or 100_000)

    # Warmup headroom: calendar days ≈ 1.6× trading days needed + buffer.
    fetch_from = period_start - timedelta(days=int(WARMUP_DAYS * 1.6) + 30)
    candles, source = await fetch_daily_candles(symbol, fetch_from, period_end)
    hist = {"source": source}

    # Index of the first bar inside the requested period
    start_unix = int(datetime(period_start.year, period_start.month,
                              period_start.day).timestamp())
    first_idx = next((i for i, c in enumerate(candles) if c[0] >= start_unix), None)
    if first_idx is None:
        raise ValueError("no bars inside the requested period")

    er, xr, risk = spec.entry_rules, spec.exit_rules, spec.risk
    max_open = max(1, risk.max_concurrent) if er.trigger == "SCHEDULE" else 1
    day_codes = {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI"}

    open_pos: list[EqTrade] = []
    closed: list[EqTrade] = []
    available = capital
    skipped_capital = 0
    pending_entry: str | None = None     # signal fired on prev close → enter at today's open

    prev_feats: dict[str, float] | None = None
    daily_loss_date: date | None = None
    daily_loss_inr = 0.0

    for i in range(first_idx, len(candles)):
        ts, o, hi, lo, c_close, _vol = candles[i][:6]
        bar_date = datetime.utcfromtimestamp(ts).date()

        # Reset the daily-loss bucket on a new day
        if daily_loss_date != bar_date:
            daily_loss_date, daily_loss_inr = bar_date, 0.0

        # ── 1. Fill pending entry at today's open ──────────────────
        if pending_entry and len(open_pos) < max_open:
            entry_px = o * (1 + FRICTION["slippage_pct"])
            budget = min(risk.max_position_inr or available, available)
            qty = int(budget // entry_px) if entry_px > 0 else 0
            if qty >= 1:
                available -= entry_px * qty
                open_pos.append(EqTrade(
                    entry_idx=i, entry_unix=int(ts), entry_px=entry_px,
                    qty=qty, reason=pending_entry, peak_close=c_close,
                ))
            else:
                skipped_capital += 1
        pending_entry = None

        # ── 2. Manage open positions ───────────────────────────────
        still_open: list[EqTrade] = []
        for p in open_pos:
            p.lowest_low = min(p.lowest_low, lo)
            p.highest_high = max(p.highest_high, hi)
            p.mae_pct = round((p.lowest_low - p.entry_px) / p.entry_px * 100, 2)
            p.mfe_pct = round((p.highest_high - p.entry_px) / p.entry_px * 100, 2)

            sl_px = p.entry_px * (1 - xr.sl_pct)
            tp_px = p.entry_px * (1 + xr.tp_pct)
            exit_px, status = None, None

            if lo <= sl_px:                       # SL first — conservative
                exit_px = min(o, sl_px)           # gap-through fills at open
                status = "SL"
            elif hi >= tp_px:
                exit_px = max(o, tp_px)
                status = "TP"
            elif xr.trailing_sl_pct and c_close < p.peak_close * (1 - xr.trailing_sl_pct):
                exit_px, status = c_close, "TRAIL"
            elif xr.time_stop_days and (i - p.entry_idx) >= xr.time_stop_days:
                exit_px, status = c_close, "TIME"

            if exit_px is not None:
                p.exit_idx, p.exit_unix = i, int(ts)
                p.exit_px = exit_px * (1 - FRICTION["slippage_pct"])
                p.status = status
                available += p.exit_px * p.qty
                if p.net_pnl < 0:
                    daily_loss_inr += -p.net_pnl
                closed.append(p)
            else:
                p.peak_close = max(p.peak_close, c_close)
                still_open.append(p)
        open_pos = still_open

        # ── 3. Evaluate today's close for tomorrow's entry ─────────
        feats = compute_equity_features(candles, i)
        signal, reason = False, ""
        if len(open_pos) < max_open and daily_loss_inr < (risk.max_daily_loss_inr or 1e18):
            if er.trigger == "SCHEDULE":
                signal = day_codes.get(bar_date.weekday()) in er.schedule.days
                reason = "schedule"
            elif er.trigger == "SIGNAL":
                signal = all(evaluate_one_dict(cond, feats, prev_feats)
                             for cond in er.conditions)
                reason = "conditions-met"
        if signal:
            pending_entry = reason
        prev_feats = feats

    # ── 4. Close whatever's still open at the final bar ────────────
    last = candles[-1]
    for p in open_pos:
        p.exit_idx = len(candles) - 1
        p.exit_unix = int(last[0])
        p.exit_px = last[4] * (1 - FRICTION["slippage_pct"])
        p.status = "EOP"
        available += p.exit_px * p.qty
        closed.append(p)
    closed.sort(key=lambda t: t.entry_unix)

    metrics = _metrics(closed, capital)
    metrics["trades_skipped_capital"] = skipped_capital
    equity_curve = _curve(closed, capital)
    data_quality = {
        "sessions_processed": len(candles) - first_idx,
        "sessions_skipped": 0,
        "source_mix_pct": {hist.get("source", "FYERS_DAILY"): 100.0},
        "engine": "equity_eod_v1",
    }

    # ── 5. Persist ──────────────────────────────────────────────────
    async with SessionLocal() as s:
        if closed:
            rows = [{
                "id": str(uuid.uuid4()),
                "run_id": run_id,
                "strategy_id": run.strategy_id,
                "strategy_version": run.strategy_version,
                "entry_ts": datetime.utcfromtimestamp(t.entry_unix),
                "exit_ts": datetime.utcfromtimestamp(t.exit_unix),
                "entry_signal": json.dumps({
                    "reason": t.reason,
                    "entry_unix": t.entry_unix, "exit_unix": t.exit_unix,
                }),
                "exit_reason": t.status,
                "legs": json.dumps([{
                    "leg_id": spec.legs[0].leg_id,
                    "symbol": spec.universe[0],
                    "action": "BUY",
                    "qty": t.qty,
                    "entry_price": round(t.entry_px, 2),
                    "exit_price": round(t.exit_px, 2),
                    "fees_inr": round(_friction_inr(t.entry_px, t.exit_px, t.qty), 2),
                }]),
                "gross_pnl_inr": round(t.gross_pnl, 2),
                "net_pnl_inr": round(t.net_pnl, 2),
                "pnl_pct": round(t.pnl_pct, 3),
                "mae_pct": t.mae_pct,
                "mfe_pct": t.mfe_pct,
            } for t in closed]
            BATCH = 500
            for j in range(0, len(rows), BATCH):
                await s.execute(pg_insert(StrategyTrade).values(rows[j:j + BATCH]))

        row = (await s.execute(
            select(StrategyRun).where(StrategyRun.id == run_id)
        )).scalar_one()
        row.metrics = json.dumps(metrics)
        row.equity_curve = json.dumps(equity_curve)
        row.data_quality = json.dumps(data_quality)
        row.status = "COMPLETED"
        row.ended_at = datetime.utcnow()
        await s.commit()

        strat = (await s.execute(
            select(Strategy).where(
                Strategy.id == run.strategy_id,
                Strategy.version == run.strategy_version,
            )
        )).scalar_one()
        if strat.status == "DRAFT":
            strat.status = "BACKTESTED"
            await s.commit()

    log.info("equity run %s done — %d trades, ROI %.2f%%",
             run_id, metrics["total_trades"], metrics["roi_pct"] or 0)


def _metrics(trades: list[EqTrade], capital: float) -> dict[str, Any]:
    """Same keys as runner._summary_metrics so the UI renders unchanged.
    Wins are net-P&L-positive (multi-day exits like TRAIL/TIME/EOP can be
    winners even without touching the TP bracket)."""
    n = len(trades)
    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]
    pnls = [t.pnl_pct for t in trades]
    win_pcts = [t.pnl_pct for t in wins]
    loss_pcts = [t.pnl_pct for t in losses]

    final = capital + sum(t.net_pnl for t in trades)
    curve = _curve(trades, capital)
    peak, max_dd = capital, 0.0
    for pt in curve:
        peak = max(peak, pt["equity"])
        if peak > 0:
            max_dd = max(max_dd, (peak - pt["equity"]) / peak * 100)

    wmax = lmax = wcur = lcur = 0
    for t in trades:
        if t.net_pnl > 0:
            wcur += 1; lcur = 0
        else:
            lcur += 1; wcur = 0
        wmax, lmax = max(wmax, wcur), max(lmax, lcur)

    gross_win = sum(win_pcts)
    gross_loss = abs(sum(loss_pcts))
    sharpe = None
    if len(pnls) >= 2 and statistics.pstdev(pnls) > 0:
        sharpe = round(statistics.mean(pnls) / statistics.pstdev(pnls), 3)

    return {
        "total_trades": n,
        "wins": len(wins), "losses": len(losses),
        "timeouts": len([t for t in trades if t.status in ("TIME", "EOP")]),
        "win_rate": round(len(wins) / n, 3) if n else None,
        "win_rate_inr": round(len(wins) / n, 3) if n else None,
        "roi_pct": round((final - capital) / capital * 100, 2) if capital else None,
        "max_drawdown_pct": round(max_dd, 2),
        "avg_winner_pct": round(statistics.mean(win_pcts), 2) if win_pcts else None,
        "avg_loser_pct": round(statistics.mean(loss_pcts), 2) if loss_pcts else None,
        "expectancy_per_trade_pct": round(statistics.mean(pnls), 2) if pnls else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "sharpe": sharpe,
        "longest_win_streak": wmax,
        "longest_loss_streak": lmax,
        "fees_paid_inr": round(sum(
            _friction_inr(t.entry_px, t.exit_px, t.qty) for t in trades), 2),
        "final_capital": round(final, 2),
        "starting_capital": capital,
        "trades_skipped_capital": 0,
    }


def _curve(trades: list[EqTrade], capital: float) -> list[dict]:
    pts: list[dict] = [{"ts": None, "equity": capital}]
    cap = capital
    for t in trades:
        cap += t.net_pnl
        pts.append({"ts": t.exit_unix, "equity": round(cap, 2)})
    if len(pts) > 500:
        pts = pts[:: len(pts) // 500]
    return pts
