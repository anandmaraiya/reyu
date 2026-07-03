"""Paper-live daily loop for EQUITY_EOD strategies (task #74).

The 60-second intraday paper-live cycle drives options strategies; it
explicitly skips kind=EQUITY_EOD (see paper_live.cycle). Equity
strategies run on a daily cadence that mirrors the backtest semantics:

  morning_cycle()  — 09:20 IST weekdays, just after open:
      evaluate eq_* conditions on YESTERDAY's completed daily bar; if
      the signal fired, enter a paper position at the current quote
      (proxy for today's open — same next-open fill rule the backtest
      uses). SCHEDULE-trigger strategies enter on matching weekdays.

  eod_manage_cycle() — 15:40 IST weekdays, after close:
      walk every open equity paper position through the same exit
      ladder as the backtest against today's completed daily bar:
      SL (day low) → TP (day high) → trailing (close vs peak close)
      → time stop (days held). Trailing peak is persisted in the
      trade's entry_signal JSON between days.

Positions are multi-day: the PAPER run persists across days (unlike the
intraday loop's per-day runs). Only status=PAPER_LIVE strategies are
processed — real-money CNC execution for LIVE equity strategies is
future work and deliberately not wired here.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, Strategy, StrategyRun, StrategyTrade
from app.strategy.conditions import evaluate_one_dict
from app.strategy.equity_features import compute_equity_features, WARMUP_DAYS
from app.strategy.equity_runner import fetch_daily_candles, _friction_inr, FRICTION
from app.strategy.spec import StrategySpec

log = logging.getLogger("reyu.strategy.equity_paper_live")

_DAY_CODES = {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI"}


async def _equity_strategies(s: AsyncSession) -> list[Strategy]:
    """Latest-version PAPER_LIVE strategies of kind EQUITY_EOD."""
    sub = (
        select(Strategy.id, func.max(Strategy.version).label("v"))
        .where(Strategy.status == "PAPER_LIVE", Strategy.kind == "EQUITY_EOD")
        .group_by(Strategy.id).subquery()
    )
    return list((await s.execute(
        select(Strategy)
        .join(sub, (Strategy.id == sub.c.id) & (Strategy.version == sub.c.v))
    )).scalars().all())


async def _ensure_run(s: AsyncSession, strat: Strategy) -> StrategyRun:
    """One persistent PAPER run per equity strategy — positions span days,
    so we never roll runs daily like the intraday loop does."""
    row = (await s.execute(
        select(StrategyRun).where(
            StrategyRun.strategy_id == strat.id,
            StrategyRun.mode == "PAPER",
            StrategyRun.status == "RUNNING",
        ).order_by(desc(StrategyRun.started_at)).limit(1)
    )).scalar_one_or_none()
    if row:
        return row
    run = StrategyRun(
        id=str(uuid.uuid4()),
        strategy_id=strat.id, strategy_version=strat.version,
        owner_id=strat.owner_id, mode="PAPER", status="RUNNING",
        config_snapshot=strat.spec,
        params=json.dumps({"started_via": "equity_paper_live"}),
        started_at=datetime.utcnow(),
    )
    s.add(run)
    await s.flush()
    return run


async def _open_positions(s: AsyncSession, run_id: str) -> list[StrategyTrade]:
    return list((await s.execute(
        select(StrategyTrade).where(
            StrategyTrade.run_id == run_id,
            StrategyTrade.exit_ts.is_(None),
        )
    )).scalars().all())


async def _ltp(symbol: str) -> float | None:
    try:
        from app.fyers import client as fy
        q = await fy.quotes([symbol])
        for item in (q.get("d") or []):
            v = item.get("v") or {}
            if v.get("lp"):
                return float(v["lp"])
    except Exception as e:
        log.warning("ltp %s failed: %s", symbol, e)
    return None


# ── Morning: evaluate yesterday's close, enter at today's price ─────
async def morning_cycle() -> dict:
    """09:20 IST weekdays. Enter paper positions for equity strategies
    whose signal fired on yesterday's completed daily bar."""
    scanned = entered = skipped = errored = 0
    today = date.today()

    async with SessionLocal() as s:
        strats = await _equity_strategies(s)
        for strat in strats:
            scanned += 1
            try:
                spec = StrategySpec.model_validate(json.loads(strat.spec))
                run = await _ensure_run(s, strat)
                er, risk = spec.entry_rules, spec.risk

                open_pos = await _open_positions(s, run.id)
                max_open = max(1, risk.max_concurrent) if er.trigger == "SCHEDULE" else 1
                if len(open_pos) >= max_open:
                    skipped += 1
                    continue

                symbol = spec.universe[0]

                # Signal evaluation on yesterday's completed bar.
                signal, reason = False, ""
                if er.trigger == "SCHEDULE":
                    # Backtest semantics: a signal on day D fills at D+1's
                    # open — so a MON schedule fills Tuesday morning.
                    yesterday = today - timedelta(days=1)
                    while yesterday.weekday() > 4:      # roll back over weekend
                        yesterday -= timedelta(days=1)
                    signal = _DAY_CODES.get(yesterday.weekday()) in er.schedule.days
                    reason = "schedule"
                elif er.trigger == "SIGNAL":
                    fetch_from = today - timedelta(days=int(WARMUP_DAYS * 1.6) + 30)
                    candles, _src = await fetch_daily_candles(symbol, fetch_from, today)
                    # Drop today's (possibly forming) bar — signal must come
                    # from a completed day.
                    candles = [c for c in candles
                               if datetime.utcfromtimestamp(c[0] + 19800).date() < today]
                    if len(candles) < 2:
                        skipped += 1
                        continue
                    feats = compute_equity_features(candles, len(candles) - 1)
                    prev = compute_equity_features(candles, len(candles) - 2)
                    signal = all(evaluate_one_dict(c, feats, prev)
                                 for c in er.conditions)
                    reason = "conditions-met"

                if not signal:
                    skipped += 1
                    continue

                price = await _ltp(symbol)
                if not price or price <= 0:
                    skipped += 1
                    continue
                entry_px = price * (1 + FRICTION["slippage_pct"])
                qty = int((risk.max_position_inr or 50_000) // entry_px)
                if qty < 1:
                    skipped += 1
                    continue

                s.add(StrategyTrade(
                    id=str(uuid.uuid4()),
                    run_id=run.id,
                    strategy_id=strat.id,
                    strategy_version=strat.version,
                    entry_ts=datetime.utcnow(),
                    entry_signal=json.dumps({
                        "reason": reason, "engine": "equity_paper_live",
                        "peak_close": entry_px,       # trailing-stop state
                        "entry_date": today.isoformat(),
                    }),
                    legs=json.dumps([{
                        "leg_id": spec.legs[0].leg_id,
                        "symbol": symbol,
                        "action": "BUY",
                        "qty": qty,
                        "entry_price": round(entry_px, 2),
                        "exit_price": None,
                        "fees_inr": None,             # computed at close
                    }]),
                ))
                entered += 1

                try:
                    from app.digest import alert_trade_opened
                    await alert_trade_opened(strat.owner_id, strat.name, "PAPER",
                                             symbol, qty, entry_px)
                except Exception:
                    pass
            except Exception as e:
                errored += 1
                log.exception("equity morning %s failed: %s", strat.id, e)
        await s.commit()

    log.info("equity morning cycle: scanned=%d entered=%d skipped=%d errored=%d",
             scanned, entered, skipped, errored)
    return {"scanned": scanned, "entered": entered,
            "skipped": skipped, "errored": errored}


# ── EOD: run the exit ladder on today's completed bar ───────────────
async def eod_manage_cycle() -> dict:
    """15:40 IST weekdays. Apply SL/TP/trailing/time-stop to every open
    equity paper position using today's daily bar — identical ladder and
    fill rules to the backtest (SL before TP on the same day)."""
    managed = closed = errored = 0
    today = date.today()

    async with SessionLocal() as s:
        strats = await _equity_strategies(s)
        for strat in strats:
            try:
                spec = StrategySpec.model_validate(json.loads(strat.spec))
                run = (await s.execute(
                    select(StrategyRun).where(
                        StrategyRun.strategy_id == strat.id,
                        StrategyRun.mode == "PAPER",
                        StrategyRun.status == "RUNNING",
                    ).order_by(desc(StrategyRun.started_at)).limit(1)
                )).scalar_one_or_none()
                if not run:
                    continue
                open_pos = await _open_positions(s, run.id)
                if not open_pos:
                    continue

                symbol = spec.universe[0]
                candles, _src = await fetch_daily_candles(
                    symbol, today - timedelta(days=14), today, min_days=1)
                bar = next((c for c in reversed(candles)
                            if datetime.utcfromtimestamp(c[0] + 19800).date() == today),
                           None)
                if not bar:
                    continue                      # holiday / no bar today
                _ts, o, hi, lo, c_close, _v = bar[:6]
                xr = spec.exit_rules

                for t in open_pos:
                    managed += 1
                    legs = json.loads(t.legs or "[]")
                    leg = legs[0] if legs else {}
                    entry_px = float(leg.get("entry_price") or 0)
                    qty = int(leg.get("qty") or 0)
                    sig = json.loads(t.entry_signal or "{}")
                    peak = float(sig.get("peak_close") or entry_px)
                    if not entry_px or not qty:
                        continue

                    sl_px = entry_px * (1 - xr.sl_pct)
                    tp_px = entry_px * (1 + xr.tp_pct)
                    held_days = (datetime.utcnow() - (t.entry_ts or datetime.utcnow())).days
                    exit_px, status = None, None

                    if lo <= sl_px:
                        exit_px, status = min(o, sl_px), "SL"
                    elif hi >= tp_px:
                        exit_px, status = max(o, tp_px), "TP"
                    elif xr.trailing_sl_pct and c_close < peak * (1 - xr.trailing_sl_pct):
                        exit_px, status = c_close, "TRAIL"
                    elif xr.time_stop_days and held_days >= xr.time_stop_days:
                        exit_px, status = c_close, "TIME"

                    if exit_px is None:
                        # Still open — roll the trailing peak forward.
                        if c_close > peak:
                            sig["peak_close"] = c_close
                            t.entry_signal = json.dumps(sig)
                        continue

                    fill = exit_px * (1 - FRICTION["slippage_pct"])
                    fees = _friction_inr(entry_px, fill, qty)
                    gross = (fill - entry_px) * qty
                    leg["exit_price"] = round(fill, 2)
                    leg["fees_inr"] = round(fees, 2)
                    t.legs = json.dumps([leg] + legs[1:])
                    t.exit_ts = datetime.utcnow()
                    t.exit_reason = status
                    t.gross_pnl_inr = round(gross, 2)
                    t.net_pnl_inr = round(gross - fees, 2)
                    t.pnl_pct = round((gross - fees) / (entry_px * qty) * 100, 3) \
                        if entry_px * qty else 0.0
                    closed += 1

                    try:
                        from app.digest import alert_trade_closed
                        await alert_trade_closed(strat.owner_id, strat.name, "PAPER",
                                                 symbol, status, float(t.net_pnl_inr))
                    except Exception:
                        pass
            except Exception as e:
                errored += 1
                log.exception("equity eod %s failed: %s", strat.id, e)
        await s.commit()

    log.info("equity eod cycle: managed=%d closed=%d errored=%d",
             managed, closed, errored)
    return {"managed": managed, "closed": closed, "errored": errored}
