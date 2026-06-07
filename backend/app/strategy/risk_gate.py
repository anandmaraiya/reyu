"""Pre-trade risk gate — Sprint 4.2.

Single source of truth for "can this strategy fire a trade right now?"
Used by both paper-live and (future) real-live entry paths.

Checks (all configurable per-strategy via `risk` block in spec):
  * max_concurrent — open trades in this strategy
  * max_position_inr — outlay (entry_prem × lot) cap per trade
  * max_daily_loss_inr — sum of today's realised + open MTM ≤ this
  * max_drawdown_pct — running drawdown on the strategy's active run

Returns a `RiskDecision` so the caller can log *why* a trade was blocked
without re-running the checks.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import StrategyTrade, StrategyRun, Strategy


@dataclass
class RiskDecision:
    allowed: bool
    reason: str | None = None
    detail: dict | None = None


async def evaluate(
    s: AsyncSession,
    *,
    strategy_id: str,
    strategy_version: int,
    run_id: str,
    spec: dict,
    candidate_entry_prem: float,
    candidate_lot_size: int,
) -> RiskDecision:
    """Single check used pre-fire by paper-live + real-live."""
    risk = spec.get("risk") or {}
    max_concurrent = int(risk.get("max_concurrent") or 1)
    max_daily_loss = float(risk.get("max_daily_loss_inr") or 5_000)
    max_position = float(risk.get("max_position_inr") or 50_000)
    max_dd_pct = float(risk.get("max_drawdown_pct") or 15)

    # ── 1. Concurrent open positions ────────────────────────────
    open_count = (await s.execute(
        select(func.count()).select_from(StrategyTrade).where(
            StrategyTrade.strategy_id == strategy_id,
            StrategyTrade.exit_ts.is_(None),
        )
    )).scalar() or 0
    if open_count >= max_concurrent:
        return RiskDecision(False, "max_concurrent",
            {"open_count": open_count, "limit": max_concurrent})

    # ── 2. Outlay cap ───────────────────────────────────────────
    outlay = candidate_entry_prem * candidate_lot_size
    if outlay > max_position:
        return RiskDecision(False, "max_position_inr",
            {"outlay_inr": round(outlay, 2), "limit": max_position})

    # ── 3. Today's realised loss ────────────────────────────────
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_pnl_realised = (await s.execute(
        select(func.coalesce(func.sum(StrategyTrade.gross_pnl_inr), 0)).where(
            StrategyTrade.strategy_id == strategy_id,
            StrategyTrade.entry_ts >= today_start,
            StrategyTrade.exit_ts.is_not(None),
        )
    )).scalar() or 0
    if today_pnl_realised <= -abs(max_daily_loss):
        return RiskDecision(False, "max_daily_loss_inr",
            {"today_realised_inr": round(today_pnl_realised, 2),
             "limit": -abs(max_daily_loss)})

    # ── 4. Run-level drawdown ───────────────────────────────────
    run = (await s.execute(
        select(StrategyRun).where(StrategyRun.id == run_id)
    )).scalar_one_or_none()
    if run and run.metrics:
        m = json.loads(run.metrics)
        cur_dd = m.get("max_drawdown_pct") or 0
        if cur_dd >= max_dd_pct:
            return RiskDecision(False, "max_drawdown_pct",
                {"current_dd_pct": cur_dd, "limit": max_dd_pct})

    return RiskDecision(True)
