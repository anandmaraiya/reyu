"""Reinforcement-learning / contextual-bandit trading endpoints.

GET    /api/rl/policies                  — list all underlyings + their model state
GET    /api/rl/policy/{underlying}       — full weights + feature names
POST   /api/rl/policy/{underlying}/reset — wipe weights, reset counters
POST   /api/rl/policy/{underlying}/toggle?on=true|false
GET    /api/rl/recommendations           — current strongest LONG/SHORT signals
GET    /api/rl/trades                    — paper-trade history (filter by status)
POST   /api/rl/decide-now                — trigger one inference cycle (debug)
POST   /api/rl/train                     — trigger training on closed trades
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, RLPolicy, RLTrade
from app.rl.features import FEATURE_NAMES, FEATURE_DIM
from app.rl.inference import decide_universe, score_universe
from app.rl.trainer import train_on_closed_trades
from app.rl.policy import Policy, ACTIONS
from app.fno_universe import all_high_priority

router = APIRouter()


@router.get("/policies")
async def list_policies(s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(RLPolicy).order_by(desc(RLPolicy.n_trades)))).scalars().all()
    return [{
        "underlying": r.underlying,
        "n_trades": r.n_trades, "n_wins": r.n_wins,
        "win_rate": round(r.n_wins / r.n_trades, 3) if r.n_trades else None,
        "cum_reward": r.cum_reward, "epsilon": r.epsilon,
        "enabled": r.enabled,
        "last_trained_at": r.last_trained_at.isoformat() if r.last_trained_at else None,
    } for r in rows]


@router.get("/policy/{underlying:path}")
async def get_policy(underlying: str, s: AsyncSession = Depends(get_session)):
    row = (await s.execute(select(RLPolicy).where(RLPolicy.underlying == underlying))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Policy not initialised for this underlying yet")
    pol = Policy.from_json(row.weights)
    return {
        "underlying": underlying,
        "n_trades": row.n_trades, "n_wins": row.n_wins, "cum_reward": row.cum_reward,
        "epsilon": row.epsilon, "enabled": row.enabled,
        "baseline": pol.baseline, "n_updates": pol.n_updates,
        "feature_names": FEATURE_NAMES,
        "w_long": pol.w_long, "w_short": pol.w_short,
        "b_long": pol.b_long, "b_short": pol.b_short,
        "feature_mean": pol.mu, "feature_std": pol.sigma,
    }


@router.post("/policy/{underlying:path}/reset")
async def reset_policy(underlying: str, s: AsyncSession = Depends(get_session)):
    row = (await s.execute(select(RLPolicy).where(RLPolicy.underlying == underlying))).scalar_one_or_none()
    if not row:
        row = RLPolicy(underlying=underlying, weights="{}", epsilon=0.10, enabled=True)
        s.add(row)
    else:
        row.weights = "{}"; row.n_trades = 0; row.n_wins = 0
        row.cum_reward = 0.0; row.last_trained_at = None
    await s.commit()
    return {"ok": True, "underlying": underlying}


@router.post("/policy/{underlying:path}/toggle")
async def toggle_policy(underlying: str, on: bool = Query(True), s: AsyncSession = Depends(get_session)):
    await s.execute(update(RLPolicy).where(RLPolicy.underlying == underlying).values(enabled=on))
    await s.commit()
    return {"ok": True, "underlying": underlying, "enabled": on}


@router.get("/recommendations")
async def recommendations(top: int = Query(20, ge=1, le=200),
                          min_conviction: float = Query(0.10, ge=0.0, le=1.0)):
    """Strongest current signals across the universe — read-only, opens no trades."""
    scores = await score_universe()
    actionable = [s for s in scores if s["action"] != "FLAT" and s["conviction"] >= min_conviction]
    actionable.sort(key=lambda r: -r["conviction"])
    return {"count": len(actionable), "top": actionable[:top]}


@router.get("/trades")
async def list_trades(
    underlying: str | None = None,
    status: str | None = Query(None, regex="^(OPEN|TP|SL|TIMEOUT)$"),
    limit: int = Query(50, ge=1, le=500),
    s: AsyncSession = Depends(get_session),
):
    q = select(RLTrade).order_by(desc(RLTrade.entry_ts)).limit(limit)
    if underlying:
        q = q.where(RLTrade.underlying == underlying)
    if status:
        q = q.where(RLTrade.status == status)
    rows = (await s.execute(q)).scalars().all()
    return [{
        "id": r.id, "underlying": r.underlying,
        "action": r.action, "leg_symbol": r.leg_symbol,
        "strike": r.strike, "option_type": r.option_type,
        "entry_ts": r.entry_ts.isoformat() if r.entry_ts else None,
        "entry_premium": r.entry_premium, "target_premium": r.target_premium, "stop_premium": r.stop_premium,
        "exit_ts": r.exit_ts.isoformat() if r.exit_ts else None,
        "exit_premium": r.exit_premium,
        "status": r.status, "reward": r.reward, "pnl_pct": r.pnl_pct,
        "paper": r.paper,
    } for r in rows]


@router.get("/summary")
async def summary(s: AsyncSession = Depends(get_session)):
    """Universe-wide health stats."""
    total_policies = (await s.execute(select(func.count()).select_from(RLPolicy))).scalar() or 0
    enabled = (await s.execute(select(func.count()).select_from(RLPolicy).where(RLPolicy.enabled.is_(True)))).scalar() or 0
    open_trades = (await s.execute(select(func.count()).select_from(RLTrade).where(RLTrade.status == "OPEN"))).scalar() or 0
    total_trades = (await s.execute(select(func.count()).select_from(RLTrade))).scalar() or 0
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    todays_trades = (await s.execute(
        select(func.count()).select_from(RLTrade).where(RLTrade.entry_ts >= today)
    )).scalar() or 0
    todays_reward = (await s.execute(
        select(func.coalesce(func.sum(RLTrade.reward), 0)).where(
            RLTrade.entry_ts >= today, RLTrade.reward.is_not(None))
    )).scalar() or 0
    return {
        "policies": total_policies, "enabled": enabled,
        "open_trades": open_trades, "total_trades": total_trades,
        "todays_trades": todays_trades, "todays_cum_reward": float(todays_reward),
        "feature_dim": FEATURE_DIM,
    }


@router.post("/decide-now")
async def decide_now(symbols: list[str] | None = None):
    """Force one inference cycle right now (debug)."""
    res = await decide_universe(symbols=symbols, paper=True)
    return {"ran": len(res), "results": res}


@router.post("/train")
async def trigger_train(s: AsyncSession = Depends(get_session)):
    res = await train_on_closed_trades(s)
    return {"updated": res}
