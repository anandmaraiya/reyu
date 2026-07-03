"""Paper-live scheduler subscription — Sprint 4.1.

Every 60 s during NSE trading hours, this job:
  1. Loads all PAPER_LIVE strategies across all owners
  2. For each, ensures a `mode=PAPER` active run exists (or creates one)
  3. Extracts live features for the strategy's universe
  4. Evaluates entry conditions via `app.strategy.conditions`
  5. Runs the pre-trade risk gate
  6. Opens a paper trade in `strategy_trades` (also writes leg into RLTrade
     for the existing sweep cycle to close on TP/SL via `rl/env.py`)

Exit/PnL detection reuses the existing 1-min RL sweep cycle — TP/SL is
shared infrastructure. When a trade closes, a follow-up tick updates the
strategy_trades row with exit_ts / gross_pnl_inr / pnl_pct / exit_reason.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import (
    SessionLocal, Strategy, StrategyRun, StrategyTrade, RLTrade,
)
from app.rl.calendar import is_trading_hours
from app.rl.features import extract as extract_features
from app.fyers.symbols import resolve as resolve_symbol
from app.strategy.conditions import entry_allowed
from app.strategy.spec import StrategySpec
from app.strategy.risk_gate import evaluate as risk_eval
from app.strategy.rl_bridge import load_policy_for_strategy, bandit_decide
from app.rl.env import enter_trade as rl_enter_trade

log = logging.getLogger("reyu.strategy.paper_live")


async def cycle() -> dict:
    """One sweep — called by the scheduler every 60 s.
    Returns a tiny summary {scanned, fired, blocked}."""
    if not is_trading_hours():
        return {"skipped": "market-closed"}

    scanned = fired = blocked = errored = 0
    block_reasons: dict[str, int] = {}

    async with SessionLocal() as s:
        # Latest-version PAPER_LIVE strategies, all owners
        # EQUITY_EOD strategies run on a daily cadence in
        # app.strategy.equity_paper_live — not this intraday loop.
        sub = (
            select(Strategy.id, func.max(Strategy.version).label("v"))
            .where(Strategy.status == "PAPER_LIVE",
                   Strategy.kind != "EQUITY_EOD")
            .group_by(Strategy.id).subquery()
        )
        strats = (await s.execute(
            select(Strategy)
            .join(sub, (Strategy.id == sub.c.id) & (Strategy.version == sub.c.v))
        )).scalars().all()

        for strat in strats:
            scanned += 1
            try:
                spec_dict = json.loads(strat.spec)
                spec = StrategySpec.model_validate(spec_dict)
                res = await _fire_one(s, strat, spec)
                if res["fired"]:
                    fired += 1
                elif res.get("blocked"):
                    blocked += 1
                    block_reasons[res["blocked"]] = block_reasons.get(res["blocked"], 0) + 1
            except Exception as e:
                errored += 1
                log.exception("paper-live %s failed: %s", strat.id, e)
        await s.commit()

    log.info("paper-live cycle: scanned=%d fired=%d blocked=%d errored=%d blocks=%s",
             scanned, fired, blocked, errored, block_reasons)
    return {"scanned": scanned, "fired": fired, "blocked": blocked,
            "errored": errored, "block_reasons": block_reasons}


async def _ensure_paper_run(
    s: AsyncSession, strat: Strategy, spec_json: str,
) -> StrategyRun:
    """Return today's active PAPER run; create one if missing."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    row = (await s.execute(
        select(StrategyRun).where(
            StrategyRun.strategy_id == strat.id,
            StrategyRun.mode == "PAPER",
            StrategyRun.status == "RUNNING",
            StrategyRun.started_at >= today_start - timedelta(days=2),
        ).order_by(desc(StrategyRun.started_at)).limit(1)
    )).scalar_one_or_none()
    if row:
        return row
    run = StrategyRun(
        id=str(uuid.uuid4()),
        strategy_id=strat.id, strategy_version=strat.version,
        owner_id=strat.owner_id, mode="PAPER", status="RUNNING",
        config_snapshot=spec_json,
        params=json.dumps({"started_via": "paper_live_cycle"}),
        started_at=datetime.utcnow(),
    )
    s.add(run)
    await s.flush()
    return run


async def _fire_one(
    s: AsyncSession, strat: Strategy, spec: StrategySpec,
) -> dict:
    """Try to fire one trade for `strat`. Returns {fired, blocked?}."""
    underlying = spec.universe[0]

    # ── 1. Extract live features ────────────────────────────────
    state = await extract_features(s, underlying)
    if not state:
        return {"fired": False, "blocked": "no-features"}
    features = state["features"]

    # ── 2. Pick action based on kind ────────────────────────────
    if spec.kind == "RL_BANDIT":
        assert spec.bandit is not None
        loaded = await load_policy_for_strategy(s, spec.bandit.underlying)
        if not loaded:
            return {"fired": False, "blocked": "no-rl-policy"}
        policy, meta = loaded
        d = bandit_decide(policy, features, spec.bandit.min_conviction, epsilon=0.0)
        action = d["action"]
        policy_version = meta.get("policy_version")
    else:
        # CONDITIONAL — schedule + conditions must pass
        ok, reason = entry_allowed(spec.entry_rules, features, datetime.utcnow())
        if not ok:
            return {"fired": False, "blocked": reason}
        first = spec.legs[0]
        # Direction = BUY CE / SELL PE = LONG; BUY PE / SELL CE = SHORT
        action = ("LONG" if (
            (first.action == "BUY" and first.option_type == "CE") or
            (first.action == "SELL" and first.option_type == "PE")
        ) else "SHORT")
        policy_version = None
    if action == "FLAT":
        return {"fired": False, "blocked": "flat"}

    # ── 3. Run / risk gate ──────────────────────────────────────
    run = await _ensure_paper_run(s, strat, strat.spec)

    # Need a candidate entry premium for outlay check. Use the bandit's
    # entry path which uses live chain; reuse rl/env.enter_trade for
    # actually opening the leg (it knows ATM strike + Fyers symbol).
    info = await resolve_symbol(underlying)
    lot_size = info.lot_size or 1

    # Open through bandit's env — it handles ATM selection + writes
    # to rl_trade for the sweep cycle to close on TP/SL.
    rl_trade = await rl_enter_trade(
        s, underlying=underlying, action=action,
        features=features, action_logprob=0.0,
        qty=1, paper=True,
    )
    if rl_trade is None:
        return {"fired": False, "blocked": "rl-enter-failed"}

    # Pre-fire risk gate (after we know real entry premium)
    decision = await risk_eval(
        s,
        strategy_id=strat.id, strategy_version=strat.version,
        run_id=run.id, spec=json.loads(strat.spec),
        candidate_entry_prem=rl_trade.entry_premium,
        candidate_lot_size=lot_size,
    )
    if not decision.allowed:
        # Roll the rl_trade back — mark it closed at entry (no movement)
        rl_trade.status = "TIMEOUT"
        rl_trade.exit_ts = datetime.utcnow()
        rl_trade.exit_premium = rl_trade.entry_premium
        rl_trade.reward = 0.0
        rl_trade.pnl_pct = 0.0
        return {"fired": False, "blocked": decision.reason}

    # ── 4. Mirror into strategy_trades ──────────────────────────
    st = StrategyTrade(
        id=str(uuid.uuid4()),
        run_id=run.id,
        strategy_id=strat.id,
        strategy_version=strat.version,
        entry_ts=rl_trade.entry_ts or datetime.utcnow(),
        entry_signal=json.dumps({
            "action": action, "features": features[:18],  # cap size
            "rl_trade_id": rl_trade.id,
        }),
        legs=json.dumps([{
            "leg_id": "L1",
            "symbol": rl_trade.leg_symbol,
            "action": "BUY",
            "qty": lot_size,
            "entry_price": rl_trade.entry_premium,
            "exit_price": None,
            "fees_inr": 65.0,                    # rough; recomputed at close
        }]),
        policy_version=policy_version,
    )
    s.add(st)

    # Owner alert (Telegram, fire-and-forget) — P2b
    try:
        from app.digest import alert_trade_opened
        await alert_trade_opened(
            strat.owner_id, strat.name, run.mode,
            rl_trade.leg_symbol or "", lot_size, rl_trade.entry_premium or 0,
        )
    except Exception:
        pass
    return {"fired": True}


async def reconcile_closed_trades() -> dict:
    """Update strategy_trades rows for paper trades whose linked RLTrade
    has closed. Called by the same scheduler tick as `cycle`."""
    updated = 0
    async with SessionLocal() as s:
        open_st = (await s.execute(
            select(StrategyTrade).where(StrategyTrade.exit_ts.is_(None))
        )).scalars().all()
        for st in open_st:
            try:
                sig = json.loads(st.entry_signal or "{}")
                rl_id = sig.get("rl_trade_id")
                if not rl_id:
                    continue
                rl = (await s.execute(
                    select(RLTrade).where(RLTrade.id == rl_id)
                )).scalar_one_or_none()
                if not rl or rl.status == "OPEN":
                    continue
                legs = json.loads(st.legs or "[]")
                if legs:
                    legs[0]["exit_price"] = rl.exit_premium
                qty = legs[0]["qty"] if legs else 1
                gross = (rl.exit_premium - rl.entry_premium) * qty if rl.exit_premium else 0
                st.exit_ts = rl.exit_ts or datetime.utcnow()
                st.exit_reason = rl.status
                st.legs = json.dumps(legs)
                st.gross_pnl_inr = round(gross, 2)
                st.pnl_pct = round(rl.pnl_pct or 0, 3)
                updated += 1

                # Owner alert on close (Telegram, fire-and-forget) — P2b
                try:
                    from app.db import Strategy as _Strat, StrategyRun as _Run
                    from app.digest import alert_trade_closed
                    run_row = (await s.execute(
                        select(_Run).where(_Run.id == st.run_id)
                    )).scalar_one_or_none()
                    strat_row = (await s.execute(
                        select(_Strat).where(
                            _Strat.id == st.strategy_id,
                            _Strat.version == st.strategy_version,
                        )
                    )).scalar_one_or_none()
                    if strat_row:
                        await alert_trade_closed(
                            strat_row.owner_id, strat_row.name,
                            run_row.mode if run_row else "PAPER",
                            (legs[0].get("symbol") if legs else "") or "",
                            st.exit_reason or "CLOSED", float(st.gross_pnl_inr or 0),
                        )
                except Exception:
                    pass
            except Exception as e:
                log.exception("reconcile %s failed: %s", st.id, e)
        await s.commit()
    if updated:
        log.info("paper-live reconcile: %d trades closed", updated)
    return {"reconciled": updated}
