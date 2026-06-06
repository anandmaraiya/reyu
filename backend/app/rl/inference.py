"""Live inference loop.

For each enabled underlying, every 5 minutes:
  1. Extract feature vector.
  2. Load (or initialise) its policy.
  3. Sample an action with ε-greedy exploration.
  4. If LONG or SHORT, and no open trade already exists for this underlying,
     open a paper trade via env.enter_trade.

Recommendations endpoint also calls `score_universe()` to surface the
strongest LONG/SHORT signals across the entire 187-symbol universe without
opening a trade — UI uses this for "should I look at X right now" hints.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import RLPolicy, RLTrade, SessionLocal
from app.rl.features import extract, FEATURE_NAMES
from app.rl.policy import Policy, ACTIONS, adjusted_epsilon
from app.rl import env as rl_env
from app.fno_universe import all_high_priority

log = logging.getLogger("reyu.rl.inference")
INFERENCE_CONCURRENCY = 8


async def _decide_one(s: AsyncSession, underlying: str, paper: bool = True) -> dict[str, Any]:
    """Single-underlying inference. Returns trace info for telemetry."""
    state = await extract(s, underlying)
    if not state:
        return {"underlying": underlying, "skipped": "no-features"}

    pol_row = (await s.execute(
        select(RLPolicy).where(RLPolicy.underlying == underlying)
    )).scalar_one_or_none()
    if pol_row is None:
        pol_row = RLPolicy(underlying=underlying, weights="{}", epsilon=0.10, enabled=True)
        s.add(pol_row)
        await s.flush()
    if not pol_row.enabled:
        return {"underlying": underlying, "skipped": "disabled"}

    pol = Policy.from_json(pol_row.weights)
    eps = adjusted_epsilon(pol_row.epsilon or 0.10, pol_row.n_trades or 0)
    min_conv = pol_row.min_conviction or 0.0
    action_idx, logprob, probs = pol.act(state["features"], eps, min_conviction=min_conv)
    action = ACTIONS[action_idx]

    # Don't double-open positions for the same underlying
    already_open = (await s.execute(
        select(func.count()).select_from(RLTrade)
        .where(RLTrade.underlying == underlying, RLTrade.status == "OPEN")
    )).scalar() or 0

    trade_id = None
    if action in ("LONG", "SHORT") and already_open == 0:
        t = await rl_env.enter_trade(
            s, underlying=underlying, action=action,
            features=state["features"], action_logprob=logprob,
            qty=1, paper=paper,
        )
        if t:
            trade_id = t.id

    await s.commit()
    return {
        "underlying": underlying,
        "action": action,
        "probs": {a: round(p, 3) for a, p in zip(ACTIONS, probs)},
        "epsilon": eps,
        "trade_id": trade_id,
        "already_open": already_open,
        "ltp": state["context"]["ltp"],
    }


async def decide_universe(symbols: list[str] | None = None, paper: bool = True) -> list[dict]:
    """Fan out decisions across the universe with bounded concurrency."""
    syms = symbols if symbols is not None else all_high_priority()
    sem = asyncio.Semaphore(INFERENCE_CONCURRENCY)

    async def _one(sym):
        async with sem, SessionLocal() as s:
            try:
                return await _decide_one(s, sym, paper=paper)
            except Exception as e:
                log.exception("inference failed for %s: %s", sym, e)
                return {"underlying": sym, "error": str(e)}

    return await asyncio.gather(*[_one(s) for s in syms])


async def score_universe(symbols: list[str] | None = None) -> list[dict]:
    """Read-only — what would the policy do RIGHT NOW for each ticker? No
    trade is opened. Used by the recommendations endpoint."""
    syms = symbols if symbols is not None else all_high_priority()
    sem = asyncio.Semaphore(INFERENCE_CONCURRENCY)

    async def _score(sym):
        async with sem, SessionLocal() as s:
            state = await extract(s, sym)
            if not state:
                return None
            row = (await s.execute(
                select(RLPolicy).where(RLPolicy.underlying == sym)
            )).scalar_one_or_none()
            pol = Policy.from_json(row.weights if row else None)
            sc = pol.scores(state["features"])
            probs = Policy._softmax(sc)
            top_idx = max(range(3), key=lambda i: probs[i])
            return {
                "underlying": sym,
                "action": ACTIONS[top_idx],
                "conviction": round(probs[top_idx] - max(probs[i] for i in range(3) if i != top_idx), 3),
                "probs": {a: round(p, 3) for a, p in zip(ACTIONS, probs)},
                "ltp": state["context"]["ltp"],
                "n_trades": (row.n_trades if row else 0),
            }

    results = await asyncio.gather(*[_score(s) for s in syms])
    return [r for r in results if r]
