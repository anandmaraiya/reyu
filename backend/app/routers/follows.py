"""Copy-trade follow endpoints (F-A11 MVP).

Follow = user A subscribes to user B's published strategy. On follow,
we clone the strategy into A's account (same as catalog copy) and
mark the relationship so the fan-out worker can mirror trades.

Endpoints:
    POST   /api/follows                       — follow a leader strategy
    DELETE /api/follows/{leader_strategy_id}  — unfollow
    GET    /api/follows                       — list my follows
    GET    /api/strategies/{id}/followers     — count + preview of followers
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text

from app.db import SessionLocal, Strategy
from app.routers.user_auth import require_user

log = logging.getLogger("reyu.follows")
router = APIRouter(prefix="/api/follows", tags=["follows"])


class FollowRequest(BaseModel):
    leader_strategy_id: str
    mode: str = "PAPER"          # PAPER | LIVE (LIVE reserved — requires algo tier)


@router.post("")
async def follow(req: FollowRequest, user: dict = Depends(require_user)):
    """Subscribe to a leader's strategy. Clones the leader's spec into the
    follower's account (as DRAFT) and records the follow relationship."""
    if req.mode not in ("PAPER", "LIVE"):
        raise HTTPException(400, "mode must be PAPER or LIVE")
    if req.mode == "LIVE" and user.get("tier") != "algo":
        raise HTTPException(403, "LIVE follows require Algo tier")

    async with SessionLocal() as s:
        # Leader strategy must exist and be published
        leader = (await s.execute(
            select(Strategy).where(
                Strategy.id == req.leader_strategy_id,
                Strategy.is_published == True,
            ).order_by(Strategy.version.desc()).limit(1)
        )).scalar_one_or_none()
        if not leader:
            raise HTTPException(404, "Leader strategy not published or not found")
        if leader.owner_id == user["sub"]:
            raise HTTPException(400, "Cannot follow your own strategy")

        # Already following?
        existing = (await s.execute(text("""
            SELECT follower_strategy_id, active
            FROM strategy_follows
            WHERE follower_id = :fid AND leader_strategy_id = :lid
        """), {"fid": user["sub"], "lid": req.leader_strategy_id})).first()

        if existing and existing.active:
            return {
                "ok": True, "message": "Already following",
                "follower_strategy_id": existing.follower_strategy_id,
            }

        # Clone the leader's spec into a new user-owned strategy (DRAFT).
        follower_strategy_id = str(uuid.uuid4()) if not existing else existing.follower_strategy_id
        if not existing:
            follower_strat = Strategy(
                id=follower_strategy_id,
                version=1,
                owner_id=user["sub"],
                name=f"{leader.name} · following",
                description=f"Follows {leader.name}. Auto-mirrors leader's trades.",
                kind=leader.kind,
                status="PAPER_LIVE" if req.mode == "PAPER" else "LIVE",
                tier_required=leader.tier_required,
                created_by="follow",
                spec=leader.spec,
                is_published=False,
                copies_count=0,
                copied_from_id=leader.id,
            )
            s.add(follower_strat)

        # Upsert the follow relationship
        await s.execute(text("""
            INSERT INTO strategy_follows
                (follower_id, leader_strategy_id, follower_strategy_id, mode, active)
            VALUES
                (:fid, :lid, :fsid, :mode, TRUE)
            ON CONFLICT (follower_id, leader_strategy_id)
            DO UPDATE SET mode = :mode, active = TRUE, follower_strategy_id = :fsid
        """), {
            "fid": user["sub"], "lid": req.leader_strategy_id,
            "fsid": follower_strategy_id, "mode": req.mode,
        })
        await s.commit()

    from app.audit import record as _audit
    await _audit(event_type="STRATEGY_FOLLOW",
                 actor_id=user["sub"], actor_email=user.get("email"),
                 resource_type="strategy", resource_id=req.leader_strategy_id,
                 action=f"Following in {req.mode} mode",
                 meta={"follower_strategy_id": follower_strategy_id})

    return {
        "ok": True,
        "follower_strategy_id": follower_strategy_id,
        "message": (
            "You're now following. When the leader's strategy signals, we'll "
            "mirror the trade under your account."
        ),
    }


@router.delete("/{leader_strategy_id}")
async def unfollow(leader_strategy_id: str, user: dict = Depends(require_user)):
    async with SessionLocal() as s:
        await s.execute(text("""
            UPDATE strategy_follows SET active = FALSE
            WHERE follower_id = :fid AND leader_strategy_id = :lid
        """), {"fid": user["sub"], "lid": leader_strategy_id})
        await s.commit()

    from app.audit import record as _audit
    await _audit(event_type="STRATEGY_UNFOLLOW",
                 actor_id=user["sub"], actor_email=user.get("email"),
                 resource_type="strategy", resource_id=leader_strategy_id,
                 action="Stopped following")

    return {"ok": True, "message": "Unfollowed. Existing open positions are yours to manage."}


@router.get("")
async def list_my_follows(user: dict = Depends(require_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT f.leader_strategy_id, f.follower_strategy_id, f.mode, f.created_at,
                   s.name as leader_name
            FROM strategy_follows f
            LEFT JOIN strategies s
              ON s.id = f.leader_strategy_id AND s.version = 1
            WHERE f.follower_id = :fid AND f.active = TRUE
            ORDER BY f.created_at DESC
        """), {"fid": user["sub"]})).fetchall()
    return {
        "count": len(rows),
        "follows": [
            {
                "leader_strategy_id": r.leader_strategy_id,
                "leader_name": r.leader_name,
                "follower_strategy_id": r.follower_strategy_id,
                "mode": r.mode,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# ── Follower count endpoint mounted on strategies namespace ────────
followers_router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@followers_router.get("/{strategy_id}/followers")
async def get_followers(strategy_id: str):
    """Public: total follower count for a published strategy."""
    async with SessionLocal() as s:
        count = (await s.execute(text("""
            SELECT COUNT(*) FROM strategy_follows
            WHERE leader_strategy_id = :sid AND active = TRUE
        """), {"sid": strategy_id})).scalar() or 0
    return {"strategy_id": strategy_id, "followers": int(count)}


# ── Trade fan-out (called by strategy runner when leader signals) ──
async def fan_out_trade(leader_strategy_id: str, leader_trade: dict) -> int:
    """When a leader strategy_trade is created, mirror it into every active
    follower's copy. Returns number of mirrors created.

    Called from app.strategy.runner after each trade insert.

    MVP: single-leg direct mirror. Multi-leg + LIVE broker fan-out is
    Phase 3. For LIVE follows, we still land the row but flag it — a
    later worker resolves whether to actually send broker orders.
    """
    from app.db import SessionLocal, StrategyTrade
    from sqlalchemy import text

    async with SessionLocal() as s:
        follows = (await s.execute(text("""
            SELECT follower_id, follower_strategy_id, mode
            FROM strategy_follows
            WHERE leader_strategy_id = :lid AND active = TRUE
        """), {"lid": leader_strategy_id})).fetchall()

        if not follows:
            return 0

        mirrors = 0
        for f in follows:
            # Insert a copy of the trade under the follower's strategy_id
            try:
                new_trade = StrategyTrade(
                    id=str(uuid.uuid4()),
                    run_id=leader_trade.get("run_id"),      # share leader's run for lineage
                    strategy_id=f.follower_strategy_id,
                    strategy_version=1,
                    entry_ts=leader_trade.get("entry_ts"),
                    exit_ts=leader_trade.get("exit_ts"),
                    entry_signal=json.dumps({
                        "mirrored_from": leader_strategy_id,
                        "leader_trade_id": leader_trade.get("id"),
                        "mode": f.mode,
                    }),
                    exit_reason=leader_trade.get("exit_reason"),
                    legs=leader_trade.get("legs"),
                    gross_pnl_inr=leader_trade.get("gross_pnl_inr"),
                    net_pnl_inr=leader_trade.get("net_pnl_inr"),
                    pnl_pct=leader_trade.get("pnl_pct"),
                    mae_pct=leader_trade.get("mae_pct"),
                    mfe_pct=leader_trade.get("mfe_pct"),
                )
                s.add(new_trade)
                mirrors += 1
            except Exception as e:
                log.warning("mirror trade for %s failed: %s", f.follower_id, e)
        await s.commit()

    log.info("fan_out_trade leader=%s mirrors=%d", leader_strategy_id, mirrors)
    return mirrors
