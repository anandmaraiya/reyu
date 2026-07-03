"""Public creator profiles (P3, task #78).

    GET /api/creators/{user_id} — display name + published strategies
                                  with forward-test facts and copy counts.

Compliance: profiles show FACTS only — what's published, how long each
strategy has forward-tested on-platform, copy/follower counts. Never
P&L, never returns, never rankings. Only the creator's display name is
exposed; email and account details stay private.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func, text

from app.db import SessionLocal, Strategy, User

log = logging.getLogger("reyu.creators")
router = APIRouter(prefix="/api/creators", tags=["creators"])


@router.get("/{user_id}")
async def creator_profile(user_id: str):
    async with SessionLocal() as s:
        u = (await s.execute(
            select(User).where(User.id == user_id, User.is_active == True)
        )).scalar_one_or_none()
        if not u:
            raise HTTPException(404, "Creator not found")

        # Latest published version per strategy owned by this creator
        latest = (
            select(Strategy.id, func.max(Strategy.version).label("v"))
            .where(Strategy.owner_id == user_id, Strategy.is_published == True)
            .group_by(Strategy.id).subquery()
        )
        strats = (await s.execute(
            select(Strategy).join(
                latest,
                (Strategy.id == latest.c.id) & (Strategy.version == latest.c.v),
            ).order_by(Strategy.published_at.desc())
        )).scalars().all()

        sids = [st.id for st in strats]
        ft: dict[str, dict] = {}
        followers: dict[str, int] = {}
        if sids:
            ft_rows = (await s.execute(text("""
                SELECT r.strategy_id,
                       COUNT(DISTINCT DATE(t.entry_ts)) AS traded_days,
                       COUNT(t.id)                      AS trades
                FROM strategy_runs r
                LEFT JOIN strategy_trades t ON t.run_id = r.id
                WHERE r.mode IN ('PAPER','LIVE') AND r.strategy_id = ANY(:sids)
                GROUP BY r.strategy_id
            """), {"sids": sids})).fetchall()
            ft = {r.strategy_id: {"forward_traded_days": int(r.traded_days or 0),
                                  "forward_trades": int(r.trades or 0)}
                  for r in ft_rows}
            f_rows = (await s.execute(text("""
                SELECT leader_strategy_id, COUNT(*) AS n
                FROM strategy_follows
                WHERE leader_strategy_id = ANY(:sids) AND active = TRUE
                GROUP BY leader_strategy_id
            """), {"sids": sids})).fetchall()
            followers = {r.leader_strategy_id: int(r.n) for r in f_rows}

    def _preview(spec_json: str) -> dict:
        try:
            spec = json.loads(spec_json or "{}")
            return {"kind": spec.get("kind"),
                    "underlying": (spec.get("universe") or [None])[0]}
        except Exception:
            return {}

    total_copies = sum(st.copies_count or 0 for st in strats)
    return {
        "creator": {
            "id": u.id,
            "display_name": u.display_name or "Reyu trader",
            "member_since": u.created_at.date().isoformat() if u.created_at else None,
        },
        "totals": {
            "published_strategies": len(strats),
            "total_copies": total_copies,
            "total_followers": sum(followers.values()),
        },
        "strategies": [
            {
                "id": st.id,
                "name": st.name,
                "description": st.description or "",
                "kind": st.kind,
                "published_at": st.published_at.isoformat() if st.published_at else None,
                "copies_count": st.copies_count or 0,
                "followers": followers.get(st.id, 0),
                "preview": _preview(st.spec),
                "forward_test": ft.get(st.id) or
                    {"forward_traded_days": 0, "forward_trades": 0},
            }
            for st in strats
        ],
    }
