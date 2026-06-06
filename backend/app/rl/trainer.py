"""Bandit trainer.

Two entrypoints:
  - `train_on_closed_trades()` — sweep all closed RL trades that haven't
    been applied to their policy yet, run the gradient update, save
    back. Idempotent via a `trained` audit field on the row (here we use
    `reward IS NOT NULL AND status != 'OPEN'` + a sentinel marker on
    the policy: we batch process and mark `last_trained_at` to the most
    recent `exit_ts` we've consumed).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import RLPolicy, RLTrade
from app.rl.policy import Policy, ACTIONS

log = logging.getLogger("reyu.rl.trainer")


async def _load_policy(s: AsyncSession, underlying: str) -> tuple[RLPolicy, Policy]:
    row = (await s.execute(
        select(RLPolicy).where(RLPolicy.underlying == underlying)
    )).scalar_one_or_none()
    if not row:
        row = RLPolicy(underlying=underlying, weights="{}", epsilon=0.10, enabled=True)
        s.add(row)
        await s.flush()
    pol = Policy.from_json(row.weights)
    return row, pol


async def _save_policy(s: AsyncSession, row: RLPolicy, pol: Policy,
                       last_ts: datetime | None = None,
                       n_trade_increment: int = 0, win_increment: int = 0,
                       reward_increment: float = 0.0) -> None:
    row.weights = pol.to_json()
    row.n_trades = (row.n_trades or 0) + n_trade_increment
    row.n_wins = (row.n_wins or 0) + win_increment
    row.cum_reward = (row.cum_reward or 0) + reward_increment
    if last_ts:
        row.last_trained_at = last_ts


async def train_on_closed_trades(s: AsyncSession, batch_limit: int = 500) -> dict:
    """Apply policy gradient updates to all closed trades newer than the
    policy's `last_trained_at`. Returns per-underlying counts."""
    # Pull policies in one shot so we know each ticker's cursor
    policies = (await s.execute(select(RLPolicy))).scalars().all()
    cursor = {p.underlying: p.last_trained_at for p in policies}

    # Closed trades that haven't been trained on yet
    q = (
        select(RLTrade)
        .where(RLTrade.status.in_(["TP", "SL", "TIMEOUT"]),
               RLTrade.reward.is_not(None))
        .order_by(RLTrade.exit_ts)
        .limit(batch_limit)
    )
    trades = (await s.execute(q)).scalars().all()

    per_under: dict[str, dict] = {}
    for t in trades:
        last_ts = cursor.get(t.underlying)
        if last_ts and t.exit_ts and t.exit_ts <= last_ts:
            continue
        try:
            features = json.loads(t.features or "[]")
            if not features:
                continue
        except Exception:
            continue
        action_idx = ACTIONS.index(t.action) if t.action in ACTIONS else None
        if action_idx is None:
            continue

        row, pol = await _load_policy(s, t.underlying)
        info = pol.update(features, action_idx, float(t.reward))
        await _save_policy(
            s, row, pol, last_ts=t.exit_ts,
            n_trade_increment=1,
            win_increment=1 if t.reward > 0 else 0,
            reward_increment=float(t.reward),
        )
        slot = per_under.setdefault(t.underlying, {"trades": 0, "cum_reward": 0.0})
        slot["trades"] += 1
        slot["cum_reward"] += float(t.reward)

    await s.commit()
    log.info("RL trainer applied %d updates across %d underlyings",
             sum(v["trades"] for v in per_under.values()), len(per_under))
    return per_under
