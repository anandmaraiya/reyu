"""Strategy-builder tools for the chat agent — Sprint 3.

Three tools:
  * create_strategy: validates a StrategySpec, persists as DRAFT for the
    caller, links the chat session.
  * list_my_strategies: surfaces the caller's strategies for context.
  * backtest_strategy: kicks a backtest run on an existing strategy.

The agent (LLM or rule-router) collects the spec conversationally — the
tools just persist + report. Each tool returns the conventional
{text, data} shape so the existing chat router renders them uniformly.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import select, func, desc

from app.db import SessionLocal, Strategy, StrategyRun
from app.strategy.spec import StrategySpec, TIER_CAPS
from app.strategy.runner import start_backtest_run, execute_run

log = logging.getLogger("reyu.agent.strategy_tools")


def _owner_of(user: dict | None) -> str | None:
    if not user:
        return None
    return user.get("sub") or user.get("user_id") or user.get("key_id")


def _tier_of(user: dict | None) -> str:
    return (user or {}).get("tier") or "free"


# ── Tool: create_strategy ──────────────────────────────────────────
async def t_create_strategy(args: dict, user: dict | None) -> dict:
    owner = _owner_of(user)
    if not owner:
        return {
            "text": "I need you to be signed in to save a strategy. "
                    "Log in first then try again."
        }

    # Two call styles:
    #   { "spec": { full StrategySpec JSON } }                — power-user
    #   { name, universe, action, option_type, tp_pct, sl_pct, … } — agent-shorthand
    spec_dict = args.get("spec")
    if not spec_dict:
        spec_dict = _build_shorthand_spec(args)

    if not spec_dict:
        return {
            "text": "Tell me at least: a name, the underlying, BUY/SELL, "
                    "option type (CE/PE), and TP/SL%. Example: "
                    "*\"Create a strategy: buy NIFTY ATM CE if PCR > 1.2, TP 25 SL 15\"*"
        }

    try:
        spec = StrategySpec.model_validate(spec_dict)
    except ValidationError as e:
        # Surface the first 2 errors cleanly
        msgs = []
        for err in e.errors()[:2]:
            loc = ".".join(str(x) for x in err["loc"])
            msgs.append(f"`{loc}`: {err['msg']}")
        return {"text": "Spec doesn't validate yet:\n" + "\n".join(msgs)}

    # Tier cap check
    tier = _tier_of(user)
    cap = TIER_CAPS.get(tier, TIER_CAPS["free"])["max_strategies"]
    async with SessionLocal() as s:
        have = (await s.execute(
            select(func.count(func.distinct(Strategy.id)))
            .where(Strategy.owner_id == owner, Strategy.status != "ARCHIVED")
        )).scalar() or 0
        if have >= cap:
            return {
                "text": f"Tier `{tier}` allows {cap} active strategies; "
                        f"you have {have}. Archive an old one or upgrade."
            }

        sid = str(uuid.uuid4())
        row = Strategy(
            id=sid, version=1, owner_id=owner,
            name=spec.name, description=spec.description,
            kind=spec.kind, status="DRAFT",
            tier_required=spec.tier_required,
            created_by="chatbot",
            chatbot_session_id=args.get("chat_session_id"),
            spec=spec.model_dump_json(),
            tags=json.dumps(spec.tags),
        )
        s.add(row)
        await s.commit()

    return {
        "text": (
            f"✓ Created **{spec.name}** as DRAFT (v1).\n"
            f"Universe: {spec.universe[0]} · TP {spec.exit_rules.tp_pct*100:.0f}% / "
            f"SL {spec.exit_rules.sl_pct*100:.0f}% · trigger {spec.entry_rules.trigger}.\n"
            f"Open it in [My Strategies](/strategies/{sid})."
        ),
        "data": {
            "strategy_id": sid,
            "version": 1,
            "status": "DRAFT",
            "spec": spec.model_dump(),
        },
    }


def _build_shorthand_spec(args: dict) -> dict | None:
    """Translate flat agent args into a full StrategySpec dict.
    Returns None if minimum fields aren't present."""
    name = args.get("name") or args.get("strategy_name")
    universe = args.get("universe")
    if isinstance(universe, str):
        universe = [universe]
    underlying = (universe or [None])[0] or args.get("underlying")
    if underlying and not universe:
        universe = [underlying]
    action = (args.get("action") or "BUY").upper()
    opt = (args.get("option_type") or "CE").upper()
    tp = args.get("tp_pct") or 0.25
    sl = args.get("sl_pct") or 0.15

    if not (name and universe and tp and sl):
        return None

    # Conditions — if user gave a single (feature, op, value), wrap.
    # Also accept a list of {feature, op, value} via `conditions`.
    cond = list(args.get("conditions") or [])
    if args.get("feature") and args.get("op") and args.get("value") is not None:
        cond.append({
            "feature": args["feature"],
            "op": args["op"],
            "value": args["value"],
        })

    # ── EQUITY_EOD shorthand — daily-bar cash-equity strategy ───────
    # Selected explicitly via kind, or inferred from eq_* features /
    # an -EQ symbol with instrument_type EQUITY.
    is_equity = (
        (args.get("kind") or "").upper() == "EQUITY_EOD"
        or (args.get("instrument_type") or "").upper() == "EQUITY"
        or any(str(c.get("feature", "")).startswith("eq_") for c in cond)
    )
    if is_equity:
        return {
            "name": name,
            "description": args.get("description"),
            "kind": "EQUITY_EOD",
            "tier_required": args.get("tier_required") or "free",
            "universe": universe,
            "legs": [{
                "leg_id": "L1",
                "action": "BUY",
                "instrument_type": "EQUITY",
                "qty_lots": 1,
            }],
            "entry_rules": {
                "trigger": "SIGNAL" if cond else "SCHEDULE",
                "schedule": {
                    "days": args.get("days") or ["MON", "TUE", "WED", "THU", "FRI"],
                    "time_window": "09:15-15:30",
                },
                "conditions": cond,
            },
            "exit_rules": {
                "tp_pct": float(tp),
                "sl_pct": float(sl),
                "trailing_sl_pct": (float(args["trailing_sl_pct"])
                                    if args.get("trailing_sl_pct") else None),
                "time_stop_days": (int(args["time_stop_days"])
                                   if args.get("time_stop_days") else None),
            },
            "risk": {
                "max_concurrent": int(args.get("max_concurrent") or 1),
                "max_daily_loss_inr": float(args.get("max_daily_loss_inr") or 10000),
                "max_position_inr": float(args.get("max_position_inr") or 50000),
            },
            "tags": args.get("tags") or [],
        }

    return {
        "name": name,
        "description": args.get("description"),
        "kind": "CONDITIONAL",
        "tier_required": args.get("tier_required") or "free",
        "universe": universe,
        "legs": [{
            "leg_id": "L1",
            "action": action,
            "instrument_type": "OPTION",
            "option_type": opt,
            "strike": {"mode": "ATM_OFFSET", "offset": int(args.get("strike_offset") or 0)},
            "expiry": {"mode": "WEEKLY", "offset": 0},
            "qty_lots": int(args.get("qty_lots") or 1),
        }],
        "entry_rules": {
            "trigger": "SIGNAL" if cond else "SCHEDULE",
            "schedule": {
                "days": args.get("days") or ["MON", "TUE", "WED", "THU", "FRI"],
                "time_window": args.get("time_window") or "09:15-15:30",
            },
            "conditions": cond,
        },
        "exit_rules": {
            "tp_pct": float(tp),
            "sl_pct": float(sl),
            "exit_at_close": True,
        },
        "risk": {
            "max_concurrent": int(args.get("max_concurrent") or 1),
            "max_daily_loss_inr": float(args.get("max_daily_loss_inr") or 5000),
            "max_position_inr": float(args.get("max_position_inr") or 20000),
        },
        "tags": args.get("tags") or [],
    }


# ── Tool: list_my_strategies ───────────────────────────────────────
async def t_list_my_strategies(args: dict, user: dict | None) -> dict:
    owner = _owner_of(user)
    if not owner:
        return {"text": "Sign in to see your strategies."}
    async with SessionLocal() as s:
        sub = (
            select(Strategy.id, func.max(Strategy.version).label("v"))
            .where(Strategy.owner_id == owner)
            .group_by(Strategy.id).subquery()
        )
        rows = (await s.execute(
            select(Strategy)
            .join(sub, (Strategy.id == sub.c.id) & (Strategy.version == sub.c.v))
            .order_by(desc(Strategy.updated_at)).limit(20)
        )).scalars().all()

    if not rows:
        return {
            "text": "You don't have any strategies yet. "
                    "Try: *\"create a strategy that buys NIFTY ATM CE on PCR > 1.2 with TP 25 SL 15\"*."
        }

    lines = [f"You have **{len(rows)}** strategies:"]
    for r in rows[:10]:
        spec = json.loads(r.spec or "{}")
        u = (spec.get("universe") or ["—"])[0]
        ex = spec.get("exit_rules", {})
        lines.append(
            f"  • **{r.name}** (v{r.version}, {r.status}) — {u} · "
            f"TP{ex.get('tp_pct', 0)*100:.0f}/SL{ex.get('sl_pct', 0)*100:.0f}"
        )
    if len(rows) > 10:
        lines.append(f"  …and {len(rows) - 10} more.")
    return {
        "text": "\n".join(lines),
        "data": {"count": len(rows), "items": [
            {"id": r.id, "name": r.name, "status": r.status,
             "version": r.version, "kind": r.kind}
            for r in rows
        ]},
    }


# ── Tool: backtest_strategy ────────────────────────────────────────
async def t_backtest_strategy(args: dict, user: dict | None) -> dict:
    owner = _owner_of(user)
    if not owner:
        return {"text": "Sign in to run a backtest."}

    sid = args.get("strategy_id") or args.get("id")
    name_hint = args.get("name")
    days = int(args.get("days") or 90)
    capital = float(args.get("starting_capital") or 100_000)

    # Resolve by id or by name
    async with SessionLocal() as s:
        if sid:
            v = (await s.execute(
                select(func.max(Strategy.version)).where(
                    Strategy.id == sid, Strategy.owner_id == owner,
                )
            )).scalar()
            if v is None:
                return {"text": f"Strategy `{sid}` not found in your account."}
            target_id, target_v = sid, v
        elif name_hint:
            row = (await s.execute(
                select(Strategy).where(
                    Strategy.owner_id == owner,
                    Strategy.name.ilike(f"%{name_hint}%"),
                ).order_by(desc(Strategy.updated_at)).limit(1)
            )).scalar_one_or_none()
            if not row:
                return {"text": f"No strategy with a name like `{name_hint}`."}
            target_id, target_v = row.id, row.version
        else:
            return {"text": "Pick a strategy: give me the id or part of the name."}

    today = date.today()
    start = (today - timedelta(days=days)).isoformat()
    end = today.isoformat()

    try:
        run_id = await start_backtest_run(
            strategy_id=target_id, strategy_version=target_v,
            owner_id=owner,
            params={
                "period_start": start, "period_end": end,
                "starting_capital": capital, "seed": 42,
            },
        )
    except ValueError as e:
        return {"text": f"Couldn't start the backtest: {e}"}

    # Fire-and-forget — runner picks it up async
    import asyncio
    asyncio.create_task(execute_run(run_id))

    return {
        "text": (
            f"✓ Backtest queued for **{name_hint or target_id[:8]}** "
            f"({start} → {end}, ₹{capital:,.0f}).\n"
            f"Run id: `{run_id[:8]}` — check progress at "
            f"[/strategies/{target_id}](/strategies/{target_id})."
        ),
        "data": {"run_id": run_id, "strategy_id": target_id, "period": [start, end]},
    }
