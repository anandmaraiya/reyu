"""Public strategy catalog + copy-to-account (F-A6).

Three endpoints:
  GET  /api/catalog                 List all published strategies (public — no auth needed)
  POST /api/catalog/{id}/copy       Copy a published strategy into your account (auth required)
  POST /api/strategies/{id}/publish Toggle publish state on your OWN strategy (auth required)

Design principles:
  - Only the LATEST version of a strategy can be published; a copy freezes
    the spec at that version so upstream edits don't retroactively change
    a copier's strategy.
  - Copy tracks lineage via `copied_from_id` so we can eventually show
    "N users copied this" leaderboards + attribute leaderboard credit.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc, func

from app.db import SessionLocal, Strategy
from app.routers.user_auth import require_user

log = logging.getLogger("reyu.catalog")
router = APIRouter(prefix="/api/catalog", tags=["catalog"])


# ── Public list ───────────────────────────────────────────────────────
@router.get("")
async def list_published(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("recent", regex="^(recent|popular)$"),
):
    """Public catalog — no auth, no user data leaked.

    Only the highest-version row per strategy is returned to keep the
    catalog free of stale variants."""
    async with SessionLocal() as s:
        # Highest version per strategy_id that is published
        latest_versions = (
            select(
                Strategy.id,
                func.max(Strategy.version).label("max_v"),
            )
            .where(Strategy.is_published == True)
            .group_by(Strategy.id)
            .subquery()
        )
        q = (
            select(Strategy)
            .join(
                latest_versions,
                (Strategy.id == latest_versions.c.id) &
                (Strategy.version == latest_versions.c.max_v),
            )
        )
        if sort == "popular":
            q = q.order_by(desc(Strategy.copies_count))
        else:
            q = q.order_by(desc(Strategy.published_at))
        q = q.limit(limit).offset(offset)

        rows = (await s.execute(q)).scalars().all()

        # Creator display names (public name only — never email). Powers
        # the "by <name>" link to /creators/{id} on catalog cards.
        creators: dict[str, str] = {}
        if rows:
            from app.db import User as _User
            owner_ids = list({r.owner_id for r in rows if r.owner_id})
            if owner_ids:
                u_rows = (await s.execute(
                    select(_User.id, _User.display_name)
                    .where(_User.id.in_(owner_ids))
                )).fetchall()
                creators = {u.id: (u.display_name or "Reyu trader") for u in u_rows}

        # Forward-test facts (P3 creator trust): how long each published
        # strategy has ACTUALLY paper/live-traded on-platform and how many
        # trades that produced. Pure facts — no returns shown, no ranking.
        ft: dict[str, dict] = {}
        if rows:
            from sqlalchemy import text as _text
            ft_rows = (await s.execute(_text("""
                SELECT r.strategy_id,
                       COUNT(DISTINCT DATE(t.entry_ts))       AS traded_days,
                       COUNT(t.id)                            AS trades,
                       MIN(r.started_at)                      AS since
                FROM strategy_runs r
                LEFT JOIN strategy_trades t ON t.run_id = r.id
                WHERE r.mode IN ('PAPER','LIVE')
                  AND r.strategy_id = ANY(:sids)
                GROUP BY r.strategy_id
            """), {"sids": [r.id for r in rows]})).fetchall()
            ft = {r.strategy_id: {
                "forward_traded_days": int(r.traded_days or 0),
                "forward_trades": int(r.trades or 0),
                "forward_since": r.since.date().isoformat() if r.since else None,
            } for r in ft_rows}

    def _preview_spec(spec_json: str) -> dict:
        try:
            spec = json.loads(spec_json or "{}")
            # Strip owner-specific / sensitive fields, keep just the shape
            return {
                "kind": spec.get("kind"),
                "underlying": spec.get("underlying") or spec.get("bandit", {}).get("underlying"),
                "brackets": spec.get("brackets") or {
                    "target_pct": spec.get("target_pct"),
                    "stop_pct": spec.get("stop_pct"),
                },
            }
        except Exception:
            return {}

    return {
        "sort": sort, "count": len(rows), "limit": limit, "offset": offset,
        "strategies": [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description or "",
                "kind": r.kind,
                "version": r.version,
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "copies_count": r.copies_count or 0,
                "preview": _preview_spec(r.spec),
                "forward_test": ft.get(r.id) or {
                    "forward_traded_days": 0, "forward_trades": 0,
                    "forward_since": None,
                },
                "creator": {
                    "id": r.owner_id,
                    "display_name": creators.get(r.owner_id, "Reyu trader"),
                },
            }
            for r in rows
        ],
    }


@router.get("/{strategy_id}/results")
async def published_results(strategy_id: str):
    """Public: on-platform run results for a PUBLISHED strategy.

    Facts about what actually happened here — completed backtest and
    paper runs with their metrics and (trimmed) equity curves. Served
    with an explicit disclaimer; never a ranking or a claim. Only
    published strategies expose results; private ones 404."""
    from app.db import StrategyRun

    async with SessionLocal() as s:
        source = (await s.execute(
            select(Strategy)
            .where(Strategy.id == strategy_id, Strategy.is_published == True)
            .order_by(desc(Strategy.version)).limit(1)
        )).scalar_one_or_none()
        if not source:
            raise HTTPException(404, "Strategy not found or not published")

        runs = (await s.execute(
            select(StrategyRun).where(
                StrategyRun.strategy_id == strategy_id,
                StrategyRun.status.in_(["COMPLETED", "RUNNING", "HALTED"]),
            ).order_by(desc(StrategyRun.started_at)).limit(10)
        )).scalars().all()

    out = []
    for r in runs:
        m = json.loads(r.metrics) if r.metrics else {}
        curve = json.loads(r.equity_curve) if r.equity_curve else []
        if len(curve) > 100:                       # trim payload for cards
            curve = curve[:: max(1, len(curve) // 100)]
        p = json.loads(r.params or "{}")
        out.append({
            "run_id": r.id,
            "mode": r.mode,                         # BACKTEST | PAPER | LIVE
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "period_start": p.get("period_start"),
            "period_end": p.get("period_end"),
            "metrics": {k: m.get(k) for k in (
                "total_trades", "win_rate", "roi_pct", "max_drawdown_pct",
                "profit_factor", "sharpe", "starting_capital")},
            "equity_curve": curve,
        })

    return {
        "strategy_id": strategy_id,
        "name": source.name,
        "runs": out,
        "disclaimer": (
            "These are records of runs executed on this platform by the "
            "creator. Backtest results are hypothetical; paper results are "
            "simulated fills. Past or simulated performance does not predict "
            "future results, and nothing here is investment advice or a "
            "performance claim."
        ),
    }


class CopyRequest(BaseModel):
    rename: Optional[str] = None            # optional new name for the copy


@router.post("/{strategy_id}/copy")
async def copy_to_account(
    strategy_id: str,
    req: CopyRequest,
    user: dict = Depends(require_user),
):
    """Duplicate a published strategy into the caller's account. Freezes
    the spec at whichever version is currently latest-published."""
    async with SessionLocal() as s:
        # Find latest published version of this strategy_id
        source = (await s.execute(
            select(Strategy)
            .where(Strategy.id == strategy_id, Strategy.is_published == True)
            .order_by(desc(Strategy.version)).limit(1)
        )).scalar_one_or_none()

        if not source:
            raise HTTPException(404, "Strategy not found or not published")

        # Build a new user-owned strategy with fresh id, version 1
        new_id = str(uuid.uuid4())
        copy = Strategy(
            id=new_id,
            version=1,
            owner_id=user["sub"],
            name=req.rename or f"{source.name} (copy)",
            description=source.description,
            kind=source.kind,
            status="DRAFT",                    # copies always start as DRAFT
            tier_required=source.tier_required,
            created_by="catalog_copy",
            spec=source.spec,
            is_published=False,
            copies_count=0,
            copied_from_id=strategy_id,
        )
        s.add(copy)

        # Increment source copies_count on ALL versions of that strategy_id
        # so ranking updates across versions. Simple UPDATE ... WHERE.
        from sqlalchemy import update
        await s.execute(
            update(Strategy)
            .where(Strategy.id == strategy_id)
            .values(copies_count=Strategy.copies_count + 1)
        )
        await s.commit()

    from app.audit import record as _audit
    await _audit(event_type="STRATEGY_COPY", actor_id=user["sub"],
                 actor_email=user.get("email"),
                 resource_type="strategy", resource_id=new_id,
                 action=f"Copied from {source.name}",
                 meta={"source_id": strategy_id, "source_version": source.version})

    return {
        "ok": True,
        "id": new_id,
        "name": copy.name,
        "message": f"'{copy.name}' added to your Saved strategies as DRAFT. Backtest, then promote to paper-live.",
    }


# ── Strategy publish toggle (owner-only) ──────────────────────────────
publish_router = APIRouter(prefix="/api/strategies", tags=["strategies"])


class PublishRequest(BaseModel):
    published: bool


@publish_router.post("/{strategy_id}/publish")
async def toggle_publish(
    strategy_id: str,
    req: PublishRequest,
    user: dict = Depends(require_user),
):
    """Toggle publish state — owner-only. Publishing exposes the LATEST
    version of the strategy in the public catalog. Un-publishing hides
    all versions."""
    async with SessionLocal() as s:
        # Must own strategy — look at the version-1 row (owner is same across versions)
        row = (await s.execute(
            select(Strategy).where(Strategy.id == strategy_id).order_by(desc(Strategy.version)).limit(1)
        )).scalar_one_or_none()
        if not row:
            raise HTTPException(404, "Strategy not found")
        if row.owner_id != user["sub"]:
            raise HTTPException(403, "You can only publish your own strategies")

        # Toggle publish on ALL versions of this strategy_id
        from sqlalchemy import update
        await s.execute(
            update(Strategy)
            .where(Strategy.id == strategy_id)
            .values(
                is_published=req.published,
                published_at=datetime.utcnow() if req.published else None,
            )
        )
        await s.commit()

    from app.audit import record as _audit
    await _audit(
        event_type="STRATEGY_PUBLISH" if req.published else "STRATEGY_UNPUBLISH",
        actor_id=user["sub"], actor_email=user.get("email"),
        resource_type="strategy", resource_id=strategy_id,
        action=f"Set is_published={req.published}",
    )

    return {"ok": True, "id": strategy_id, "published": req.published}
