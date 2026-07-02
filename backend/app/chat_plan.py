"""Multi-turn chat plan state (F-A10).

Elevates each session from a series of independent questions into a
running conversation with memory. The plan captures:

  goal          — what the user is trying to achieve this session
  underlying    — active symbol they're working on
  bias          — bullish / bearish / range
  brackets      — target/stop pct they've decided on
  strategy_draft — legs, tier_required, mode
  decisions     — history of "we picked X because Y" moments
  next_step     — what Reyu suggests do next

Persisted per session in Redis. Injected into every LLM system prompt
so subsequent turns build on prior context instead of restarting from
scratch.

Design principle: the plan is *inferred* by the LLM itself, not by the
user typing structured fields. `update_plan()` accepts a partial
merge — the LLM can nudge state via a tool call `update_chat_plan`.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

log = logging.getLogger("reyu.chat_plan")

PLAN_TTL_SEC = 7 * 24 * 60 * 60           # 7d — matches session TTL
PLAN_KEY = "chat:plan:{sid}"


def _empty_plan() -> dict:
    return {
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "goal": None,
        "underlying": None,
        "bias": None,
        "brackets": None,          # {target_pct, stop_pct}
        "strategy_draft": None,    # partial spec
        "decisions": [],           # [{ts, choice, why}]
        "next_step": None,
    }


async def get_plan(session_id: str) -> dict:
    """Fetch the plan for a session. Returns an empty plan if none exists."""
    from app.store import store
    raw = await store.r.get(PLAN_KEY.format(sid=session_id))
    if isinstance(raw, bytes):
        raw = raw.decode()
    if not raw:
        return _empty_plan()
    try:
        return json.loads(raw)
    except Exception:
        return _empty_plan()


async def update_plan(session_id: str, patch: dict) -> dict:
    """Merge `patch` into the current plan, persist, return the new plan.

    List fields (`decisions`) append; scalar fields overwrite. Timestamps
    always refresh."""
    plan = await get_plan(session_id)

    for key, value in patch.items():
        if key == "decisions" and isinstance(value, list):
            plan["decisions"].extend(value)
            plan["decisions"] = plan["decisions"][-20:]      # cap at 20 to keep prompt small
        elif key in plan:
            plan[key] = value

    plan["updated_at"] = datetime.utcnow().isoformat()

    from app.store import store
    await store.r.set(
        PLAN_KEY.format(sid=session_id),
        json.dumps(plan),
        ex=PLAN_TTL_SEC,
    )
    return plan


async def clear_plan(session_id: str) -> None:
    from app.store import store
    await store.r.delete(PLAN_KEY.format(sid=session_id))


def summarise_plan_for_prompt(plan: dict) -> Optional[str]:
    """Turn the plan into a short paragraph for the LLM system prompt.
    Returns None when the plan is essentially empty (nothing to feed)."""
    if not plan:
        return None
    parts: list[str] = []
    if plan.get("goal"):
        parts.append(f"Session goal: {plan['goal']}")
    if plan.get("underlying"):
        parts.append(f"Active symbol: {plan['underlying']}")
    if plan.get("bias"):
        parts.append(f"Current bias: {plan['bias']}")
    if plan.get("brackets"):
        b = plan["brackets"]
        if isinstance(b, dict) and (b.get("target_pct") or b.get("stop_pct")):
            parts.append(f"Brackets: +{b.get('target_pct')} / -{b.get('stop_pct')}")
    if plan.get("strategy_draft"):
        parts.append(f"Draft strategy: {json.dumps(plan['strategy_draft'])[:180]}")
    if plan.get("decisions"):
        recent = plan["decisions"][-3:]
        joined = "; ".join(f"{d.get('choice')}" for d in recent if d.get("choice"))
        if joined:
            parts.append(f"Recent decisions: {joined}")
    if plan.get("next_step"):
        parts.append(f"Suggested next step: {plan['next_step']}")

    if not parts:
        return None
    return "PLAN SO FAR:\n" + "\n".join(f"  - {p}" for p in parts)
