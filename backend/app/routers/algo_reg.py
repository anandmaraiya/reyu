"""SEBI algo-ID registration endpoints (F-B1).

SEBI's retail-algo framework requires broker-registered, exchange-issued
algo IDs on retail algorithmic orders. The platform-side lifecycle:

    owner:      POST /api/strategies/{id}/algo-registration   (request)
                GET  /api/strategies/{id}/algo-registration   (status)
    superadmin: GET  /api/admin/algo-registrations            (queue)
                PATCH /api/admin/algo-registrations/{id}      (record the
                       exchange-issued ID after the broker confirms)

Enforcement: when settings.enforce_algo_registration is on, LIVE
promotion requires a REGISTERED row (checked in strategies.promote) and
live orders carry the algo ID as their order tag. The flag defaults off
until the Fyers-side process is confirmed — rails first, no retrofit.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, desc

from app.db import SessionLocal, AlgoRegistration, Strategy
from app.routers.user_auth import require_user, require_superadmin

log = logging.getLogger("reyu.algo_reg")
router = APIRouter(prefix="/api/strategies", tags=["algo-registration"])
admin_router = APIRouter(prefix="/api/admin/algo-registrations",
                         tags=["algo-registration"])


def _row(r: AlgoRegistration) -> dict:
    return {
        "id": r.id, "strategy_id": r.strategy_id, "broker": r.broker,
        "exchange": r.exchange, "status": r.status,
        "exchange_algo_id": r.exchange_algo_id, "notes": r.notes,
        "requested_at": r.requested_at.isoformat() if r.requested_at else None,
        "registered_at": r.registered_at.isoformat() if r.registered_at else None,
    }


@router.post("/{strategy_id}/algo-registration")
async def request_registration(strategy_id: str, request: Request,
                               user: dict = Depends(require_user)):
    """Owner requests exchange registration for a strategy. Idempotent —
    an existing row is returned as-is. Layer 2: ownership."""
    async with SessionLocal() as s:
        strat = (await s.execute(
            select(Strategy).where(
                Strategy.id == strategy_id, Strategy.owner_id == user["sub"],
            ).order_by(desc(Strategy.version)).limit(1)
        )).scalar_one_or_none()
        if not strat:
            raise HTTPException(404, "Strategy not found")

        existing = (await s.execute(
            select(AlgoRegistration).where(
                AlgoRegistration.strategy_id == strategy_id)
        )).scalar_one_or_none()
        if existing:
            return {"ok": True, "registration": _row(existing)}

        reg = AlgoRegistration(strategy_id=strategy_id, owner_id=user["sub"])
        s.add(reg)
        await s.commit()
        result = _row(reg)

    from app.audit import record as _audit
    await _audit(event_type="ALGO_REG_REQUESTED",
                 actor_id=user["sub"], actor_email=user.get("email"),
                 resource_type="strategy", resource_id=strategy_id,
                 action="Requested exchange algo-ID registration",
                 request=request)
    return {"ok": True, "registration": result}


@router.get("/{strategy_id}/algo-registration")
async def registration_status(strategy_id: str,
                              user: dict = Depends(require_user)):
    async with SessionLocal() as s:
        reg = (await s.execute(
            select(AlgoRegistration).where(
                AlgoRegistration.strategy_id == strategy_id,
                AlgoRegistration.owner_id == user["sub"],
            )
        )).scalar_one_or_none()
    if not reg:
        return {"registration": None}
    return {"registration": _row(reg)}


# ── Superadmin: record exchange-issued IDs ──────────────────────────
class RegistrationPatch(BaseModel):
    status: str                      # REGISTERED | REJECTED
    exchange_algo_id: str | None = None
    notes: str | None = None


@admin_router.get("")
async def list_registrations(status: str | None = None,
                             _user: dict = Depends(require_superadmin)):
    async with SessionLocal() as s:
        q = select(AlgoRegistration).order_by(desc(AlgoRegistration.requested_at))
        if status:
            q = q.where(AlgoRegistration.status == status)
        rows = (await s.execute(q.limit(200))).scalars().all()
    return {"registrations": [_row(r) for r in rows]}


@admin_router.patch("/{registration_id}")
async def record_registration(registration_id: str, patch: RegistrationPatch,
                              request: Request,
                              user: dict = Depends(require_superadmin)):
    """Record the broker/exchange outcome. REGISTERED requires the
    exchange-issued algo ID."""
    if patch.status not in ("REGISTERED", "REJECTED"):
        raise HTTPException(400, "status must be REGISTERED or REJECTED")
    if patch.status == "REGISTERED" and not patch.exchange_algo_id:
        raise HTTPException(400, "REGISTERED requires exchange_algo_id")

    async with SessionLocal() as s:
        reg = (await s.execute(
            select(AlgoRegistration).where(AlgoRegistration.id == registration_id)
        )).scalar_one_or_none()
        if not reg:
            raise HTTPException(404, "Registration not found")
        reg.status = patch.status
        reg.exchange_algo_id = patch.exchange_algo_id
        reg.notes = patch.notes
        reg.registered_at = datetime.utcnow() if patch.status == "REGISTERED" else None
        await s.commit()
        result = _row(reg)

    from app.audit import record as _audit
    await _audit(event_type="ALGO_REG_" + patch.status,
                 actor_id=user["sub"], actor_email=user.get("email"),
                 resource_type="strategy", resource_id=result["strategy_id"],
                 action=f"Algo registration {patch.status}"
                        + (f" id={patch.exchange_algo_id}" if patch.exchange_algo_id else ""),
                 request=request)
    return {"ok": True, "registration": result}


# ── Gating helper (imported by strategies.promote) ──────────────────
async def registered_algo_id(strategy_id: str) -> str | None:
    """Exchange algo ID when the strategy is REGISTERED, else None."""
    async with SessionLocal() as s:
        reg = (await s.execute(
            select(AlgoRegistration).where(
                AlgoRegistration.strategy_id == strategy_id,
                AlgoRegistration.status == "REGISTERED",
            )
        )).scalar_one_or_none()
    return reg.exchange_algo_id if reg else None
