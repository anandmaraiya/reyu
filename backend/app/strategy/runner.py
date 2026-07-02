"""Backtest runner — Sprint 1.3.

Takes a `StrategySpec` + run params and drives one full backtest:

  1. Loop trading days in [period_start, period_end]
  2. Pull spot candles via `app.fyers.cache.get_candles` (cache-first)
  3. Build a decider that wraps `app.strategy.conditions.entry_allowed`
     (or the RL bridge for RL_BANDIT strategies)
  4. Hand it to `app.sim.engine.simulate_session` per day
  5. Persist trades into `strategy_trades`
  6. Compute metrics + ROI via `engine.compute_roi` w/ realistic friction
  7. Persist `strategy_runs` row with config_snapshot, metrics,
     equity_curve, data_quality

Each call is async and returns the run_id immediately so the HTTP
handler can stay snappy. The actual loop runs in the caller's
background-task context.
"""
from __future__ import annotations

import json
import uuid
import logging
import statistics
from datetime import datetime, date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import (
    SessionLocal, Strategy, StrategyRun, StrategyTrade,
)
from app.fyers import cache
from app.fyers.symbols import resolve as resolve_symbol
from app.rl.calendar import iter_trading_days
from app.sim.engine import (
    simulate_session, compute_roi, Decision, SimTrade,
    realized_iv_feature_extractor,
)
from app.strategy.conditions import entry_allowed
from app.strategy.spec import StrategySpec
from app.strategy.rl_bridge import load_policy_for_strategy, bandit_decide

log = logging.getLogger("reyu.strategy.runner")


# ── Public entry point ────────────────────────────────────────────
async def start_backtest_run(
    *,
    strategy_id: str,
    strategy_version: int,
    owner_id: str,
    params: dict[str, Any],
) -> str:
    """Persist a RUNNING row + return its id. Caller fires the actual
    work via FastAPI BackgroundTasks → `execute_run(run_id)`."""
    run_id = str(uuid.uuid4())
    async with SessionLocal() as s:
        strat = (await s.execute(
            select(Strategy).where(
                Strategy.id == strategy_id,
                Strategy.version == strategy_version,
                Strategy.owner_id == owner_id,
            )
        )).scalar_one_or_none()
        if not strat:
            raise ValueError("strategy/version not found for owner")

        row = StrategyRun(
            id=run_id, strategy_id=strategy_id,
            strategy_version=strategy_version,
            owner_id=owner_id,
            mode="BACKTEST", status="RUNNING",
            config_snapshot=strat.spec,
            params=json.dumps(params),
            started_at=datetime.utcnow(),
        )
        s.add(row)
        await s.commit()
    return run_id


async def execute_run(run_id: str) -> None:
    """Background worker — runs the full backtest, persists trades +
    metrics, flips status to COMPLETED / ERRORED."""
    try:
        await _execute_run_inner(run_id)
    except Exception as e:
        log.exception("backtest run %s failed: %s", run_id, e)
        async with SessionLocal() as s:
            row = (await s.execute(
                select(StrategyRun).where(StrategyRun.id == run_id)
            )).scalar_one_or_none()
            if row:
                row.status = "ERRORED"
                row.error_message = str(e)[:1000]
                row.ended_at = datetime.utcnow()
                await s.commit()


async def _execute_run_inner(run_id: str) -> None:
    async with SessionLocal() as s:
        run = (await s.execute(
            select(StrategyRun).where(StrategyRun.id == run_id)
        )).scalar_one_or_none()
        if not run:
            raise ValueError("run not found")

    spec_raw = json.loads(run.config_snapshot)
    spec = StrategySpec.model_validate(spec_raw)
    params = json.loads(run.params or "{}")

    underlying = spec.universe[0]
    period_start = date.fromisoformat(params["period_start"])
    period_end = date.fromisoformat(params["period_end"])
    capital = float(params.get("starting_capital") or 100_000)
    seed = params.get("seed")
    # Lot size resolution — DB ground truth from Fyers sync
    lot_size = int(params.get("lot_size") or (await resolve_symbol(underlying)).lot_size or 1)

    # ── Build the decide() callable based on `kind` ────────────────
    decide_fn = await _build_decider(spec, period_start)

    # ── Walk days ───────────────────────────────────────────────────
    all_trades: list[SimTrade] = []
    source_tally: dict[str, int] = {}
    sessions_processed = 0
    sessions_skipped = 0

    for d in iter_trading_days(period_start, period_end):
        try:
            hist = await cache.get_candles(
                underlying, resolution="5",
                range_from=d.isoformat(), range_to=d.isoformat(),
            )
        except Exception as e:
            log.warning("history %s %s failed: %s", underlying, d, e)
            sessions_skipped += 1
            continue
        candles = hist.get("candles") or []
        if len(candles) < 10:
            sessions_skipped += 1
            continue
        sessions_processed += 1
        src = hist.get("source", "L1_FORWARD_INTRADAY")
        source_tally[src] = source_tally.get(src, 0) + 1

        day_trades = simulate_session(
            candles,
            decide=decide_fn,
            target_pct=spec.exit_rules.tp_pct,
            stop_pct=spec.exit_rules.sl_pct,
            underlying=underlying,
            seed=seed,
        )
        # Attach the bar's epoch ts to the trade for ledger persistence
        for t in day_trades:
            t.entry_signal["entry_unix"] = int(candles[t.entry_idx][0])
            t.entry_signal["exit_unix"] = int(candles[t.exit_idx][0])
        all_trades.extend(day_trades)

    # ── ROI w/ realistic friction (closes NU-12b) ──────────────────
    roi = compute_roi(
        all_trades,
        starting_capital=capital,
        lot_size=lot_size,
    )

    metrics = _summary_metrics(all_trades, roi)
    equity_curve = _equity_curve(all_trades, capital, lot_size, roi["friction_model"])
    data_quality = {
        "sessions_processed": sessions_processed,
        "sessions_skipped": sessions_skipped,
        "source_mix_pct": {
            k: round(v / sessions_processed * 100, 2) if sessions_processed else 0
            for k, v in source_tally.items()
        },
    }

    # ── Persist trades + run summary ───────────────────────────────
    async with SessionLocal() as s:
        if all_trades:
            trade_rows = []
            for t in all_trades:
                entry_ts = datetime.utcfromtimestamp(t.entry_signal.get("entry_unix", 0)) \
                    if t.entry_signal.get("entry_unix") else datetime.utcnow()
                exit_ts = datetime.utcfromtimestamp(t.entry_signal.get("exit_unix", 0)) \
                    if t.entry_signal.get("exit_unix") else None
                trade_rows.append({
                    "id": str(uuid.uuid4()),
                    "run_id": run_id,
                    "strategy_id": run.strategy_id,
                    "strategy_version": run.strategy_version,
                    "entry_ts": entry_ts,
                    "exit_ts": exit_ts,
                    "entry_signal": json.dumps(t.entry_signal),
                    "exit_reason": t.status,
                    "legs": json.dumps([{
                        "leg_id": "L1",
                        "symbol": None,
                        "action": "BUY",
                        "qty": t.qty_lots * lot_size,
                        "entry_price": t.entry_prem,
                        "exit_price": t.exit_prem,
                        "fees_inr": round(roi.get("fees_inr_per_trade") or 0, 2),
                    }]),
                    "gross_pnl_inr": round(
                        (t.exit_prem - t.entry_prem) * lot_size * t.qty_lots, 2
                    ),
                    # Net = gross - all-in fees (brokerage + slippage + STT + exchange + GST).
                    # `roi.fees_inr_per_trade` is the summed friction from compute_roi().
                    "net_pnl_inr": round(
                        (t.exit_prem - t.entry_prem) * lot_size * t.qty_lots
                        - (roi.get("fees_inr_per_trade") or 0), 2
                    ),
                    "pnl_pct": round(t.pnl_pct, 3),
                    "mae_pct": t.mae_pct,
                    "mfe_pct": t.mfe_pct,
                    "policy_version": params.get("policy_version"),
                })
            # Batched UPSERT-style insert
            BATCH = 500
            for i in range(0, len(trade_rows), BATCH):
                await s.execute(pg_insert(StrategyTrade).values(trade_rows[i:i + BATCH]))

            # F-A11 fan-out: mirror each trade to every active follower's
            # copy of this strategy. Errors are logged and swallowed so a
            # follower-side hiccup can't fail the leader's trade insert.
            try:
                from app.routers.follows import fan_out_trade
                for t_row in trade_rows:
                    await fan_out_trade(run.strategy_id, t_row)
            except Exception as _e:
                import logging as _log
                _log.getLogger("reyu.runner").warning(
                    "fan_out_trade failed for run=%s: %s", run_id, _e)

        row = (await s.execute(
            select(StrategyRun).where(StrategyRun.id == run_id)
        )).scalar_one()
        row.metrics = json.dumps(metrics)
        row.equity_curve = json.dumps(equity_curve)
        row.data_quality = json.dumps(data_quality)
        row.status = "COMPLETED"
        row.ended_at = datetime.utcnow()
        await s.commit()

        # If this is the strategy's first completed run, flip status DRAFT -> BACKTESTED
        strat = (await s.execute(
            select(Strategy).where(
                Strategy.id == run.strategy_id,
                Strategy.version == run.strategy_version,
            )
        )).scalar_one()
        if strat.status == "DRAFT":
            strat.status = "BACKTESTED"
            await s.commit()

    log.info("backtest run %s done — %d trades, ROI %.2f%%, DD %.2f%%",
             run_id, metrics["total_trades"], metrics["roi_pct"], metrics["max_drawdown_pct"])


# ── Deciders ────────────────────────────────────────────────────────
async def _build_decider(spec: StrategySpec, period_start: date):
    """Returns a `decide(features, idx, ctx) -> Decision` callable."""
    if spec.kind == "RL_BANDIT":
        assert spec.bandit is not None
        async with SessionLocal() as s:
            loaded = await load_policy_for_strategy(s, spec.bandit.underlying)
        if not loaded:
            raise ValueError(f"No trained rl_policy for {spec.bandit.underlying}")
        policy, meta = loaded
        min_conv = spec.bandit.min_conviction

        # Bandit policy was trained with FEATURE_DIM (30); the strategy
        # runner's default extractor returns 18 dims (chain dims absent
        # during historical backtest). Pad zeros for missing dims so the
        # policy can score the vector — bandit weights for zero-padded
        # dims simply contribute 0 to the score.
        from app.rl.features import FEATURE_DIM as POLICY_DIM
        def _bandit_decide(features, idx, ctx):
            if len(features) < POLICY_DIM:
                features = list(features) + [0.0] * (POLICY_DIM - len(features))
            res = bandit_decide(policy, features, min_conv, epsilon=0.0)
            return Decision(action=res["action"], metadata=res)
        return _bandit_decide

    # CONDITIONAL — features eval + schedule gate
    er = spec.entry_rules
    # The condition evaluator needs a real timestamp; we synthesize from
    # bar index + period_start. Each candle in our store carries an
    # epoch unix at index 0, so we can use that.

    def _conditional_decide(features, idx, ctx):
        # ctx is loose — we don't yet thread the timestamp from
        # simulate_session. For now, schedule check is done in caller's
        # day loop (we know the day is a weekday). Intraday window
        # check uses the bar's progress as a proxy.
        progress = ctx.get("progress", 0.0)
        # Approximate IST minute-of-day from progress
        minutes_into_session = progress * (15 * 60 + 30 - (9 * 60 + 15))
        ist_min = (9 * 60 + 15) + minutes_into_session
        a, _, b = er.schedule.time_window.partition("-")
        ah, am = a.split(":"); bh, bm = b.split(":")
        win_lo = int(ah) * 60 + int(am)
        win_hi = int(bh) * 60 + int(bm)
        if not (win_lo <= ist_min <= win_hi):
            return Decision(action="FLAT", metadata={"reason": "schedule"})
        # Conditions
        for c in er.conditions:
            from app.strategy.conditions import evaluate_one
            try:
                if not evaluate_one(c, features):
                    return Decision(
                        action="FLAT",
                        metadata={"reason": f"cond:{c.feature}{c.op}{c.value}"},
                    )
            except (KeyError, IndexError):
                return Decision(action="FLAT", metadata={"reason": "feature-unavailable"})

        # All conditions passed — direction comes from first leg
        first = spec.legs[0]
        action = "LONG" if (
            (first.action == "BUY" and first.option_type == "CE") or
            (first.action == "SELL" and first.option_type == "PE")
        ) else "SHORT"
        offset = (first.strike.offset if first.strike else 0) or 0
        return Decision(
            action=action, strike_offset=offset,
            qty_lots=first.qty_lots,
            metadata={"reason": "conditions-met"},
        )
    return _conditional_decide


# ── Metrics ─────────────────────────────────────────────────────────
def _summary_metrics(trades: list[SimTrade], roi: dict) -> dict:
    n = len(trades)
    wins = [t for t in trades if t.status == "TP"]
    losses = [t for t in trades if t.status == "SL"]
    timeouts = [t for t in trades if t.status == "TIMEOUT"]
    pnls = [t.pnl_pct for t in trades]
    winning_pcts = [t.pnl_pct for t in wins]
    losing_pcts = [t.pnl_pct for t in losses]
    streaks_w, streaks_l = _streaks(trades)

    metrics = {
        "total_trades": n,
        "wins": len(wins), "losses": len(losses), "timeouts": len(timeouts),
        "win_rate": round(len(wins) / n, 3) if n else None,
        "win_rate_inr": roi.get("win_rate_inr"),
        "roi_pct": roi.get("roi_pct"),
        "max_drawdown_pct": roi.get("max_drawdown_pct"),
        "avg_winner_pct": round(statistics.mean(winning_pcts), 2) if winning_pcts else None,
        "avg_loser_pct": round(statistics.mean(losing_pcts), 2) if losing_pcts else None,
        "expectancy_per_trade_pct": round(statistics.mean(pnls), 2) if pnls else None,
        "profit_factor": _profit_factor(winning_pcts, losing_pcts),
        "sharpe": _sharpe(pnls),
        "longest_win_streak": streaks_w,
        "longest_loss_streak": streaks_l,
        "fees_paid_inr": roi.get("fees_inr_total"),
        "final_capital": roi.get("final_capital"),
        "starting_capital": roi.get("starting_capital"),
        "trades_skipped_capital": roi.get("trades_skipped_capital", 0),
    }
    return metrics


def _profit_factor(wins_pct: list[float], losses_pct: list[float]) -> float | None:
    if not wins_pct and not losses_pct:
        return None
    gross_win = sum(wins_pct) if wins_pct else 0.0
    gross_loss = abs(sum(losses_pct)) if losses_pct else 0.0
    if gross_loss == 0:
        return None
    return round(gross_win / gross_loss, 2)


def _sharpe(pnls: list[float]) -> float | None:
    """Crude per-trade Sharpe — mean / std. Not annualised."""
    if len(pnls) < 2:
        return None
    m = statistics.mean(pnls); sd = statistics.pstdev(pnls)
    if sd == 0:
        return None
    return round(m / sd, 3)


def _streaks(trades: list[SimTrade]) -> tuple[int, int]:
    wmax = lmax = wcur = lcur = 0
    for t in trades:
        if t.status == "TP":
            wcur += 1; lcur = 0
        elif t.status == "SL":
            lcur += 1; wcur = 0
        else:
            wcur = lcur = 0
        wmax = max(wmax, wcur)
        lmax = max(lmax, lcur)
    return wmax, lmax


def _equity_curve(
    trades: list[SimTrade],
    starting_capital: float,
    lot_size: int,
    friction_model: dict,
) -> list[dict]:
    """Recompute equity per trade, capped at ~500 points for response size."""
    pts: list[dict] = [{"ts": None, "equity": starting_capital}]
    cap = starting_capital
    for t in trades:
        qty = lot_size * t.qty_lots
        slip = t.entry_prem * qty * friction_model["slippage_pct"]
        stt = t.exit_prem * qty * friction_model["stt_sell_pct"]
        exch = (t.entry_prem + t.exit_prem) * qty * friction_model["exchange_pct"]
        taxes = (friction_model["brokerage_per_trade"] + exch) * friction_model["gst_pct"]
        friction = friction_model["brokerage_per_trade"] + slip + stt + exch + taxes
        cap += (t.exit_prem - t.entry_prem) * qty - friction
        pts.append({
            "ts": t.entry_signal.get("exit_unix"),
            "equity": round(cap, 2),
        })
    # Down-sample if too dense
    if len(pts) > 500:
        step = len(pts) // 500
        pts = pts[::step]
    return pts
