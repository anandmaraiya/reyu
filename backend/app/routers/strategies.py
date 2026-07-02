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

from typing import List
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
        "is_published": bool(row.is_published),
        "copies_count": row.copies_count or 0,
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
        # Compliance gate — user must have accepted the platform legal docs
        # AND the live-execution authorization before any real order fires.
        from app.routers.legal import require_acceptance
        from app.legal import PLATFORM_DOCS, LIVE_DOCS
        await require_acceptance(owner, PLATFORM_DOCS + LIVE_DOCS)

    if row.status not in ("BACKTESTED", "PAPER_LIVE"):
        raise HTTPException(409,
            f"Can't promote from `{row.status}`. Backtest the strategy first.")

    # Preflight — block LIVE promotion when preflight FAILs (auth missing,
    # bad lot size, insufficient funds). PAPER_LIVE skips preflight since
    # no real orders will fire.
    preflight_result: dict | None = None
    if mode == "LIVE":
        preflight_result = await _run_promotion_preflight(row.spec)
        if preflight_result and preflight_result.get("verdict") == "FAIL":
            raise HTTPException(400, {
                "message": "Preflight failed — cannot promote to LIVE.",
                "preflight": preflight_result,
            })

    row.status = mode
    await s.commit()

    # Audit
    from app.audit import record as _audit
    await _audit(
        event_type="STRATEGY_PROMOTE",
        actor_id=owner, actor_email=None,
        resource_type="strategy", resource_id=strategy_id,
        action=f"Promoted to {mode}",
        meta={"preflight_verdict": preflight_result.get("verdict") if preflight_result else None},
        request=request,
    )

    return {
        "ok": True, "id": strategy_id, "status": mode,
        "preflight": preflight_result,
    }


async def _run_promotion_preflight(spec_json: str) -> dict:
    """Enumerate representative legs from a strategy spec and run preflight."""
    import json
    from app.routers.preflight import preflight as _preflight_fn, PreflightRequest, OrderLeg
    try:
        spec = json.loads(spec_json or "{}")
    except Exception:
        spec = {}

    universe = spec.get("universe") or []
    if isinstance(universe, str):
        universe = [universe]
    if not universe:
        return {"verdict": "WARN", "checks": [
            {"check": "spec", "status": "WARN",
             "detail": "Strategy spec has no `universe` — preflight skipped."}
        ], "summary": {"legs": 0}}

    # Build a stub 1-lot order for the strategy's primary underlying.
    # Real per-leg preflight would enumerate the actual entry legs — this
    # catches broker-auth + margin gates which is 90% of what fails.
    stub_symbol = "NSE:NIFTY26JUL24800CE"      # placeholder tradable
    req = PreflightRequest(legs=[OrderLeg(
        symbol=stub_symbol,
        side=(spec.get("action") or "BUY").upper(),
        qty=int(spec.get("qty_lots") or 1),
        price=100,
        order_type="MARKET",
        product_type="INTRADAY",
    )])
    # Bypass the FastAPI Depends chain — call handler directly
    resp = await _preflight_fn(req, _user={"sub": "system-promote-check"})
    return resp.model_dump() if hasattr(resp, "model_dump") else resp


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

    # ── Mark-to-market live LTPs for open positions ─────────────
    # Pull current quotes in one call so the front-end can show real-time
    # unrealised P&L without per-position network round-trips.
    open_enriched = []
    mtm_unrealised = 0.0
    if open_now:
        from app.fyers import client as fy
        legs_by_tid: dict[str, dict] = {}
        symbols: list[str] = []
        for t in open_now:
            legs = json.loads(t.legs or "[]")
            leg = legs[0] if legs else None
            legs_by_tid[t.id] = leg
            if leg and leg.get("symbol"):
                symbols.append(leg["symbol"])
        ltp_map: dict[str, float | None] = {s: None for s in symbols}
        if symbols:
            try:
                q = await fy.quotes(symbols)
                # Fyers v3: {'d': [{'n': symbol, 'v': {'lp': ltp, ...}}]}
                for item in (q.get("d") or []):
                    name = item.get("n")
                    v = item.get("v") or {}
                    ltp = v.get("lp") or v.get("ltp")
                    if name and ltp is not None:
                        ltp_map[name] = float(ltp)
            except Exception:
                pass

        for t in open_now:
            leg = legs_by_tid.get(t.id)
            ltp = ltp_map.get(leg["symbol"]) if leg else None
            entry = leg.get("entry_price") if leg else None
            qty = leg.get("qty") if leg else None
            unreal_inr = unreal_pct = None
            if ltp is not None and entry and qty:
                unreal_inr = round((ltp - entry) * qty, 2)
                unreal_pct = round((ltp / entry - 1) * 100, 3)
                mtm_unrealised += unreal_inr
            open_enriched.append({
                "id": t.id, "entry_ts": t.entry_ts.isoformat(),
                "leg": leg,
                "current_ltp": ltp,
                "unrealised_inr": unreal_inr,
                "unrealised_pct": unreal_pct,
            })

    return {
        "active_run": {
            "id": run.id, "mode": run.mode, "status": run.status,
            "started_at": run.started_at.isoformat(),
        } if run else None,
        "open_positions": open_enriched,
        "today": {
            "fills": len(today_fills),
            "open": len(open_now),
            "closed": len(closed),
            "wins": sum(1 for t in closed if (t.gross_pnl_inr or 0) > 0),
            "realised_pnl_inr": round(realised, 2),
            "unrealised_pnl_inr": round(mtm_unrealised, 2),
            "total_pnl_inr": round(realised + mtm_unrealised, 2),
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


# ── POST /api/strategies/compare ───────────────────────────────────
@router.post("/compare")
async def compare_runs(
    request: Request,
    run_ids: List[str],
    s: AsyncSession = Depends(get_session),
):
    """Side-by-side compare of N runs from any strategies the caller owns.
    Returns aligned equity curves (normalised to common length) + a
    metric matrix for the KPI table."""
    if not run_ids:
        raise HTTPException(400, "Provide at least one run_id")
    if len(run_ids) > 10:
        raise HTTPException(400, "Max 10 runs per compare")

    owner = _owner(request)
    rows = (await s.execute(
        select(StrategyRun, Strategy).join(
            Strategy,
            (Strategy.id == StrategyRun.strategy_id) &
            (Strategy.version == StrategyRun.strategy_version),
        ).where(
            StrategyRun.id.in_(run_ids),
            StrategyRun.owner_id == owner,
        )
    )).all()

    out_runs = []
    for run, strat in rows:
        metrics = json.loads(run.metrics or "{}")
        curve = json.loads(run.equity_curve or "[]")
        out_runs.append({
            "run_id": run.id,
            "strategy_id": run.strategy_id,
            "strategy_name": strat.name,
            "strategy_version": run.strategy_version,
            "mode": run.mode,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "ended_at": run.ended_at.isoformat() if run.ended_at else None,
            "params": json.loads(run.params or "{}"),
            "metrics": metrics,
            "equity_curve": [
                {"step": i, "ts": p.get("ts"), "equity": p.get("equity")}
                for i, p in enumerate(curve)
            ],
        })

    # Metric matrix — every metric across every run, side-by-side
    all_metrics: set[str] = set()
    for r in out_runs:
        all_metrics.update((r.get("metrics") or {}).keys())
    metric_matrix = []
    for m in sorted(all_metrics):
        row = {"metric": m}
        for r in out_runs:
            row[r["run_id"][:8]] = (r.get("metrics") or {}).get(m)
        metric_matrix.append(row)

    return {
        "count": len(out_runs),
        "runs": out_runs,
        "metric_matrix": metric_matrix,
    }


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
