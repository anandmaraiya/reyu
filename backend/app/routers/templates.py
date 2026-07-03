"""Strategy template endpoints (P2a).

    GET  /api/templates                     list (filter ?persona=)
    GET  /api/templates/{id}                full spec preview
    POST /api/templates/{id}/copy           copy into my account as DRAFT

Templates are curated starting points (app.templates_catalog), never
recommendations. Copying validates through StrategySpec so a template
can't rot silently when the spec schema evolves.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func

from app.db import SessionLocal, Strategy
from app.routers.user_auth import require_user
from app.strategy.spec import StrategySpec, TIER_CAPS
from app.templates_catalog import PERSONAS, list_templates, get_template

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("")
async def list_all(persona: str | None = None):
    return {"personas": PERSONAS, "templates": list_templates(persona)}


@router.get("/{template_id}")
async def get_one(template_id: str):
    t = get_template(template_id)
    if not t:
        raise HTTPException(404, "Template not found")
    return t


@router.post("/{template_id}/copy")
async def copy_template(template_id: str, user: dict = Depends(require_user)):
    t = get_template(template_id)
    if not t:
        raise HTTPException(404, "Template not found")

    spec = StrategySpec.model_validate(t["spec"])   # fail loudly if schema drifted

    tier = user.get("tier", "free")
    cap = TIER_CAPS.get(tier, TIER_CAPS["free"])["max_strategies"]
    async with SessionLocal() as s:
        have = (await s.execute(
            select(func.count(func.distinct(Strategy.id)))
            .where(Strategy.owner_id == user["sub"], Strategy.status != "ARCHIVED")
        )).scalar() or 0
        if have >= cap:
            raise HTTPException(403,
                f"Tier `{tier}` allows {cap} active strategies; you have {have}.")

        sid = str(uuid.uuid4())
        s.add(Strategy(
            id=sid, version=1, owner_id=user["sub"],
            name=spec.name, description=spec.description,
            kind=spec.kind, status="DRAFT",
            tier_required=spec.tier_required,
            created_by="template",
            spec=spec.model_dump_json(),
            tags=json.dumps(spec.tags),
        ))
        await s.commit()

    from app.audit import record as _audit
    await _audit(event_type="STRATEGY_CREATE",
                 actor_id=user["sub"], actor_email=user.get("email"),
                 resource_type="strategy", resource_id=sid,
                 action=f"Copied template {template_id}",
                 meta={"template_id": template_id})

    return {"ok": True, "id": sid, "name": spec.name, "status": "DRAFT"}
