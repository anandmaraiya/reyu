"""User-strategy CRUD — Sprint 0.4.

Endpoints:
  POST   /api/strategies                         create (auto-version 1)
  GET    /api/strategies                         list mine
  GET    /api/strategies/{id}                    detail (latest version unless ?version=)
  PATCH  /api/strategies/{id}                    creates version+1 (copy-on-edit)
  POST   /api/strategies/{id}/archive
  GET    /api/strategies/{id}/versions           list all versions

Runs / trades / backtest live in Sprint 1.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, Strategy, StrategyRun, StrategyTrade
from app.strategy.spec import StrategySpec, TIER_CAPS
from app.strategy.runner import start_backtest_run, execute_run
from fastapi import BackgroundTasks

router = APIRouter()


def _owner(request: Request) -> str:
    """Resolve the calling user — auth middleware has already validated."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Unauthenticated")
    return user.get("sub") or user.get("user_id") or user.get("key_id") or "anonymous"


def _tier(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return user.get("tier") or "free"


async def _latest_version(s: AsyncSession, sid: str) -> int | None:
    return (await s.execute(
        select(func.max(Strategy.version)).where(Strategy.id == sid)
    )).scalar()


def _row_to_dict(row: Strategy) -> dict[str, Any]:
    return {
        "id": row.id,
        "version": row.version,
        "name": row.name,
        "description": row.description,
        "kind": row.kind,
        "status": row.status,
        "tier_required": row.tier_required,
        "created_by": row.created_by,
        "chatbot_session_id": row.chatbot_session_id,
        "spec": json.loads(row.spec or "{}"),
        "tags": json.loads(row.tags or "[]"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ── POST /api/strategies ────────────────────────────────────────────
@router.post("")
async def create_strategy(
    request: Request,
    spec: StrategySpec,
    created_by: str = Query("manual", regex="^(manual|chatbot|template)$"),
    chatbot_session_id: str | None = Query(None),
    s: AsyncSession = Depends(get_session),
):
    owner = _owner(request)
    tier = _tier(request)

    # Tier-based strategy-count cap
    cap = TIER_CAPS.get(tier, TIER_CAPS["free"])["max_strategies"]
    have = (await s.execute(
        select(func.count(func.distinct(Strategy.id)))
        .where(Strategy.owner_id == owner, Strategy.status != "ARCHIVED")
    )).scalar() or 0
    if have >= cap:
        raise HTTPException(403,
            f"Tier `{tier}` allows {cap} active strategies; you have {have}.")

    if spec.tier_required not in ("free", tier) and tier != "algo":
        raise HTTPException(403,
            f"Spec requires `{spec.tier_required}` tier; you have `{tier}`.")

    sid = str(uuid.uuid4())
    row = Strategy(
        id=sid, version=1, owner_id=owner,
        name=spec.name, description=spec.description,
        kind=spec.kind, status="DRAFT",
        tier_required=spec.tier_required,
        created_by=created_by,
        chatbot_session_id=chatbot_session_id,
        spec=spec.model_dump_json(),
        tags=json.dumps(spec.tags),
    )
    s.add(row)
    await s.commit()
    return {"ok": True, **_row_to_dict(row)}


# ── GET /api/strategies ─────────────────────────────────────────────
@router.get("")
async def list_strategies(
    request: Request,
    status: str | None = Query(None, regex="^(DRAFT|BACKTESTED|PAPER_LIVE|LIVE|ARCHIVED)$"),
    tag: str | None = Query(None),
    s: AsyncSession = Depends(get_session),
):
    owner = _owner(request)

    # Return latest version per id
    sub = (
        select(Strategy.id, func.max(Strategy.version).label("max_v"))
        .where(Strategy.owner_id == owner)
        .group_by(Strategy.id).subquery()
    )
    q = (
        select(Strategy)
        .join(sub, (Strategy.id == sub.c.id) & (Strategy.version == sub.c.max_v))
        .order_by(desc(Strategy.updated_at))
    )
    if status:
        q = q.where(Strategy.status == status)
    rows = (await s.execute(q)).scalars().all()

    out = [_row_to_dict(r) for r in rows]
    if tag:
        out = [r for r in out if tag in (r.get("tags") or [])]
    return {"count": len(out), "items": out}


# ── GET /api/strategies/{id} ───────────────────────────────────────
@router.get("/{strategy_id}")
async def get_strategy(
    request: Request,
    strategy_id: str,
    version: int | None = Query(None),
    s: AsyncSession = Depends(get_session),
):
    owner = _owner(request)
    v = version
    if v is None:
        v = await _latest_version(s, strategy_id)
        if v is None:
            raise HTTPException(404, "Strategy not found")

    row = (await s.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.version == v,
            Strategy.owner_id == owner,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Strategy / version not found")
    return _row_to_dict(row)


# ── PATCH /api/strategies/{id} — copy-on-edit ──────────────────────
@router.patch("/{strategy_id}")
async def update_strategy(
    request: Request,
    strategy_id: str,
    spec: StrategySpec,
    s: AsyncSession = Depends(get_session),
):
    """Creates `version+1` — existing runs keep pointing at the old
    version via `strategy_runs.strategy_version`."""
    owner = _owner(request)
    latest_v = await _latest_version(s, strategy_id)
    if latest_v is None:
        raise HTTPException(404, "Strategy not found")
    latest = (await s.execute(
        select(Strategy).where(
            Strategy.id == strategy_id, Strategy.version == latest_v,
            Strategy.owner_id == owner,
        )
    )).scalar_one_or_none()
    if not latest:
        raise HTTPException(404, "Strategy not found")
    if latest.status == "ARCHIVED":
        raise HTTPException(409, "Cannot edit an archived strategy")

    new_row = Strategy(
        id=strategy_id, version=latest_v + 1, owner_id=owner,
        name=spec.name, description=spec.description,
        kind=spec.kind, status=latest.status,
        tier_required=spec.tier_required,
        created_by=latest.created_by,
        chatbot_session_id=latest.chatbot_session_id,
        spec=spec.model_dump_json(),
        tags=json.dumps(spec.tags),
    )
    s.add(new_row)
    await s.commit()
    return {"ok": True, **_row_to_dict(new_row)}


# ── POST /api/strategies/runs/{run_id}/halt ────────────────────────
@router.post("/runs/{run_id}/halt")
async def halt_run(
    request: Request,
    run_id: str,
    s: AsyncSession = Depends(get_session),
):
    """Stop a RUNNING paper or live run cleanly.
    - Marks any open strategy_trades as MANUAL exit at last-known price
    - Flips run.status to HALTED
    - Does NOT touch RLTrade rows (those are bandit-owned)"""
    owner = _owner(request)
    run = (await s.execute(
        select(StrategyRun).where(
            StrategyRun.id == run_id, StrategyRun.owner_id == owner,
        )
    )).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status != "RUNNING":
        raise HTTPException(409, f"Run already in `{run.status}` state.")

    opens = (await s.execute(
        select(StrategyTrade).where(
            StrategyTrade.run_id == run_id,
            StrategyTrade.exit_ts.is_(None),
        )
    )).scalars().all()
    for t in opens:
        legs = json.loads(t.legs or "[]")
        if legs and legs[0].get("exit_price") is None:
            legs[0]["exit_price"] = legs[0].get("entry_price")
            t.legs = json.dumps(legs)
        t.exit_ts = datetime.utcnow()
        t.exit_reason = "MANUAL"
        t.gross_pnl_inr = 0.0
        t.pnl_pct = 0.0

    run.status = "HALTED"
    run.ended_at = datetime.utcnow()
    await s.commit()

    # Cascade: flip parent strategy from LIVE/PAPER_LIVE back to BACKTESTED
    if run.mode in ("PAPER", "LIVE"):
        strat = (await s.execute(
            select(Strategy).where(
                Strategy.id == run.strategy_id,
                Strategy.version == run.strategy_version,
            )
        )).scalar_one_or_none()
        if strat and strat.status in ("PAPER_LIVE", "LIVE"):
            strat.status = "BACKTESTED"
            await s.commit()

    return {"ok": True, "run_id": run_id, "halted_trades": len(opens),
            "status": "HALTED"}


# ── POST /api/strategies/{id}/promote ──────────────────────────────
@router.post("/{strategy_id}/promote")
async def promote_strategy(
    request: Request,
    strategy_id: str,
    mode: str = Query(..., regex="^(PAPER_LIVE|LIVE)$"),
    confirm: bool = Query(False, description="Required for LIVE mode"),
    s: AsyncSession = Depends(get_session),
):
    """Flip a BACKTESTED strategy to PAPER_LIVE or LIVE.
    PAPER_LIVE just enables the scheduler to subscribe. LIVE requires
    `confirm=true` and (future) algo-tier."""
    owner = _owner(request)
    v = await _latest_version(s, strategy_id)
    if v is None:
        raise HTTPException(404, "Strategy not found")
    row = (await s.execute(
        select(Strategy).where(
            Strategy.id == strategy_id, Strategy.version == v,
            Strategy.owner_id == owner,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Strategy not found")

    if mode == "LIVE":
        if not confirm:
            raise HTTPException(400,
                "LIVE mode requires confirm=true and an algo-tier account.")
        tier = _tier(request)
        if tier != "algo":
            raise HTTPException(403, "LIVE mode requires `algo` tier.")

    if row.status not in ("BACKTESTED", "PAPER_LIVE"):
        raise HTTPException(409,
            f"Can't promote from `{row.status}`. Backtest the strategy first.")

    row.status = mode
    await s.commit()
    return {"ok": True, "id": strategy_id, "status": mode}


# ── GET /api/strategies/{id}/live-monitor ──────────────────────────
@router.get("/{strategy_id}/live-monitor")
async def live_monitor(
    request: Request,
    strategy_id: str,
    s: AsyncSession = Depends(get_session),
):
    """Today's paper/live snapshot — open positions, today's fills, MTM PnL."""
    owner = _owner(request)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Most recent active run
    run = (await s.execute(
        select(StrategyRun).where(
            StrategyRun.strategy_id == strategy_id,
            StrategyRun.owner_id == owner,
            StrategyRun.mode.in_(["PAPER", "LIVE"]),
        ).order_by(desc(StrategyRun.started_at)).limit(1)
    )).scalar_one_or_none()

    today_fills = (await s.execute(
        select(StrategyTrade).where(
            StrategyTrade.strategy_id == strategy_id,
            StrategyTrade.entry_ts >= today_start,
        ).order_by(desc(StrategyTrade.entry_ts))
    )).scalars().all()

    open_now = [t for t in today_fills if t.exit_ts is None]
    closed = [t for t in today_fills if t.exit_ts is not None]
    realised = sum(t.gross_pnl_inr or 0 for t in closed)

    return {
        "active_run": {
            "id": run.id, "mode": run.mode, "status": run.status,
            "started_at": run.started_at.isoformat(),
        } if run else None,
        "open_positions": [{
            "id": t.id, "entry_ts": t.entry_ts.isoformat(),
            "leg": json.loads(t.legs or "[]")[0] if t.legs else None,
        } for t in open_now],
        "today": {
            "fills": len(today_fills),
            "open": len(open_now),
            "closed": len(closed),
            "wins": sum(1 for t in closed if (t.gross_pnl_inr or 0) > 0),
            "realised_pnl_inr": round(realised, 2),
        },
    }


# ── POST /api/strategies/{id}/archive ──────────────────────────────
@router.post("/{strategy_id}/archive")
async def archive_strategy(
    request: Request,
    strategy_id: str,
    s: AsyncSession = Depends(get_session),
):
    owner = _owner(request)
    v = await _latest_version(s, strategy_id)
    if v is None:
        raise HTTPException(404, "Strategy not found")
    row = (await s.execute(
        select(Strategy).where(
            Strategy.id == strategy_id, Strategy.version == v,
            Strategy.owner_id == owner,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Strategy not found")
    if row.status == "LIVE":
        raise HTTPException(409, "Halt the live run before archiving.")
    row.status = "ARCHIVED"
    await s.commit()
    return {"ok": True, "id": strategy_id, "status": "ARCHIVED"}


# ── POST /api/strategies/{id}/runs — start a backtest ─────────────
@router.post("/{strategy_id}/runs")
async def start_run(
    request: Request,
    strategy_id: str,
    background: BackgroundTasks,
    period_start: str = Query(..., description="ISO date"),
    period_end: str = Query(..., description="ISO date"),
    starting_capital: float = Query(100_000, ge=10_000, le=10_000_000),
    seed: int | None = Query(None),
    lot_size: int | None = Query(None, ge=1),
    s: AsyncSession = Depends(get_session),
):
    """Kick a backtest run for the strategy's latest version. Returns
    run_id immediately; poll GET /runs/{run_id} for status."""
    owner = _owner(request)
    v = await _latest_version(s, strategy_id)
    if v is None:
        raise HTTPException(404, "Strategy not found")

    params = {
        "period_start": period_start,
        "period_end": period_end,
        "starting_capital": starting_capital,
        "seed": seed,
        "lot_size": lot_size,
    }
    try:
        run_id = await start_backtest_run(
            strategy_id=strategy_id, strategy_version=v,
            owner_id=owner, params=params,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    background.add_task(execute_run, run_id)
    return {"ok": True, "run_id": run_id, "status": "RUNNING"}


# ── GET /api/strategies/runs/{run_id} ─────────────────────────────
@router.get("/runs/{run_id}")
async def get_run(
    request: Request,
    run_id: str,
    s: AsyncSession = Depends(get_session),
):
    owner = _owner(request)
    row = (await s.execute(
        select(StrategyRun).where(
            StrategyRun.id == run_id, StrategyRun.owner_id == owner,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Run not found")
    return {
        "id": row.id,
        "strategy_id": row.strategy_id,
        "strategy_version": row.strategy_version,
        "mode": row.mode, "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "params": json.loads(row.params or "{}"),
        "metrics": json.loads(row.metrics or "{}"),
        "custom_metrics": json.loads(row.custom_metrics or "{}"),
        "equity_curve": json.loads(row.equity_curve or "[]"),
        "data_quality": json.loads(row.data_quality or "{}"),
        "error_message": row.error_message,
    }


# ── GET /api/strategies/{id}/runs ─────────────────────────────────
@router.get("/{strategy_id}/runs")
async def list_runs(
    request: Request,
    strategy_id: str,
    mode: str | None = Query(None, regex="^(BACKTEST|PAPER|LIVE)$"),
    limit: int = Query(20, ge=1, le=200),
    s: AsyncSession = Depends(get_session),
):
    owner = _owner(request)
    q = (
        select(StrategyRun).where(
            StrategyRun.strategy_id == strategy_id,
            StrategyRun.owner_id == owner,
        ).order_by(desc(StrategyRun.started_at)).limit(limit)
    )
    if mode:
        q = q.where(StrategyRun.mode == mode)
    rows = (await s.execute(q)).scalars().all()
    return [{
        "id": r.id, "version": r.strategy_version,
        "mode": r.mode, "status": r.status,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        "metrics": json.loads(r.metrics or "{}"),
    } for r in rows]


# ── GET /api/strategies/runs/{run_id}/trades ──────────────────────
@router.get("/runs/{run_id}/trades")
async def list_run_trades(
    request: Request,
    run_id: str,
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    s: AsyncSession = Depends(get_session),
):
    owner = _owner(request)
    # ownership check via run
    run = (await s.execute(
        select(StrategyRun).where(
            StrategyRun.id == run_id, StrategyRun.owner_id == owner,
        )
    )).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Run not found")
    rows = (await s.execute(
        select(StrategyTrade).where(StrategyTrade.run_id == run_id)
        .order_by(StrategyTrade.entry_ts).limit(limit).offset(offset)
    )).scalars().all()
    return {"count": len(rows), "items": [{
        "id": t.id,
        "entry_ts": t.entry_ts.isoformat() if t.entry_ts else None,
        "exit_ts": t.exit_ts.isoformat() if t.exit_ts else None,
        "entry_signal": json.loads(t.entry_signal or "{}"),
        "exit_reason": t.exit_reason,
        "legs": json.loads(t.legs or "[]"),
        "gross_pnl_inr": t.gross_pnl_inr,
        "net_pnl_inr": t.net_pnl_inr,
        "pnl_pct": t.pnl_pct,
        "mae_pct": t.mae_pct, "mfe_pct": t.mfe_pct,
    } for t in rows]}


# ── GET /api/strategies/{id}/versions ──────────────────────────────
@router.get("/{strategy_id}/versions")
async def list_versions(
    request: Request,
    strategy_id: str,
    s: AsyncSession = Depends(get_session),
):
    owner = _owner(request)
    rows = (await s.execute(
        select(Strategy).where(
            Strategy.id == strategy_id, Strategy.owner_id == owner,
        ).order_by(desc(Strategy.version))
    )).scalars().all()
    if not rows:
        raise HTTPException(404, "Strategy not found")
    return [
        {"version": r.version, "status": r.status, "name": r.name,
         "updated_at": r.updated_at.isoformat() if r.updated_at else None}
        for r in rows
    ]
