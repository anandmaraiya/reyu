"""Bridge between user-owned strategies and the global RL bandit.

A strategy with `kind=RL_BANDIT` doesn't carry weights of its own. It
*references* a row in `rl_policy` (keyed by underlying). At decision
time, the strategy runner asks the bandit "what would you do given
these features?" — the bandit's `Policy.act()` returns LONG / SHORT /
FLAT and the strategy runner converts that into trades through the
shared simulator.

This keeps a clean separation:
  * `rl_policy` stays the source of truth for the bandit's learned
    weights (single per underlying — fine for v1)
  * `strategies` rows reference that policy by underlying + record
    `bandit.min_conviction` overrides per strategy
  * Every trade landed by an RL strategy goes into `strategy_trades`
    with `policy_version` set so audits can reproduce the decision

Phase-2 forking (private policies per Algo-tier user) is reserved but
not implemented — it would require a key-policy table keyed by
(owner_id, underlying).
"""
from __future__ import annotations

import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import RLPolicy
from app.rl.policy import Policy, ACTIONS


async def load_policy_for_strategy(
    s: AsyncSession,
    underlying: str,
) -> tuple[Policy, dict] | None:
    """Return (Policy, metadata) tuple for an RL strategy's underlying,
    or None if no policy exists yet (Algo user would need to train one
    before they can deploy)."""
    row = (await s.execute(
        select(RLPolicy).where(RLPolicy.underlying == underlying)
    )).scalar_one_or_none()
    if row is None:
        return None
    pol = Policy.from_json(row.weights)
    meta = {
        "underlying": underlying,
        "n_trades": row.n_trades or 0,
        "n_wins": row.n_wins or 0,
        "epsilon": row.epsilon or 0.10,
        "target_pct": row.target_pct,       # informational — strategy can override
        "stop_pct": row.stop_pct,
        "policy_version": f"{underlying}@{row.last_trained_at.isoformat() if row.last_trained_at else 'untrained'}",
    }
    return pol, meta


def bandit_decide(
    policy: Policy,
    features: list[float],
    min_conviction: float,
    epsilon: float = 0.0,
) -> dict:
    """Single-call decision interface used by the strategy runner. In
    live mode pass epsilon=0 for pure greedy. Returns {"action",
    "probs", "conviction"}."""
    action_idx, logprob, probs = policy.act(
        features, epsilon, min_conviction=min_conviction,
    )
    flat_idx = ACTIONS.index("FLAT")
    conviction = round(probs[action_idx] - probs[flat_idx], 3) if action_idx != flat_idx else 0.0
    return {
        "action": ACTIONS[action_idx],
        "probs": {a: round(p, 3) for a, p in zip(ACTIONS, probs)},
        "conviction": conviction,
        "logprob": logprob,
    }
