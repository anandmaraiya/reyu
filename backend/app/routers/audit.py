"""Audit trail read + export endpoints (F-A9).

Superadmin-only browse of audit_log rows + CSV export for compliance.
Rows are never editable through the API — this is read-only.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select, desc

from app.db import SessionLocal, AuditLog
from app.routers.user_auth import require_superadmin

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/log")
async def list_audit(
    days: int = Query(30, ge=1, le=730),
    event_type: Optional[str] = Query(None),
    actor_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user: dict = Depends(require_superadmin),
):
    """Paginated audit log — superadmin only. Filters by event_type + actor."""
    since = datetime.utcnow() - timedelta(days=days)
    async with SessionLocal() as s:
        q = select(AuditLog).where(AuditLog.ts >= since)
        if event_type:
            q = q.where(AuditLog.event_type == event_type)
        if actor_id:
            q = q.where(AuditLog.actor_id == actor_id)
        q = q.order_by(desc(AuditLog.ts)).limit(limit).offset(offset)
        rows = (await s.execute(q)).scalars().all()

        # Also compute the totals for pagination
        from sqlalchemy import func
        cq = select(func.count()).select_from(AuditLog).where(AuditLog.ts >= since)
        if event_type:
            cq = cq.where(AuditLog.event_type == event_type)
        if actor_id:
            cq = cq.where(AuditLog.actor_id == actor_id)
        total = (await s.execute(cq)).scalar() or 0

    return {
        "days": days,
        "total": total,
        "limit": limit,
        "offset": offset,
        "entries": [
            {
                "id": r.id,
                "ts": r.ts.isoformat() if r.ts else None,
                "actor_id": r.actor_id,
                "actor_email": r.actor_email,
                "event_type": r.event_type,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "action": r.action,
                "ip_address": r.ip_address,
                "user_agent": (r.user_agent or "")[:120],
            }
            for r in rows
        ],
    }


@router.get("/export.csv")
async def export_audit(
    days: int = Query(90, ge=1, le=1825),
    _user: dict = Depends(require_superadmin),
):
    """Full CSV export — for compliance / regulator ask."""
    since = datetime.utcnow() - timedelta(days=days)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(AuditLog).where(AuditLog.ts >= since).order_by(desc(AuditLog.ts))
        )).scalars().all()

    buf = io.StringIO()
    fieldnames = [
        "ts", "actor_email", "actor_id", "event_type",
        "resource_type", "resource_id", "action",
        "ip_address", "user_agent", "meta",
    ]
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({
            "ts": r.ts.isoformat() if r.ts else "",
            "actor_email": r.actor_email or "",
            "actor_id": r.actor_id or "",
            "event_type": r.event_type,
            "resource_type": r.resource_type or "",
            "resource_id": r.resource_id or "",
            "action": r.action or "",
            "ip_address": r.ip_address or "",
            "user_agent": (r.user_agent or "")[:200],
            "meta": r.meta or "",
        })

    filename = f"reyu-audit-{datetime.utcnow().date().isoformat()}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/event-types")
async def known_event_types(_user: dict = Depends(require_superadmin)):
    """List of event_type values present in the log — powers the filter dropdown."""
    async with SessionLocal() as s:
        from sqlalchemy import distinct
        rows = (await s.execute(select(distinct(AuditLog.event_type)))).all()
    return {"event_types": sorted([r[0] for r in rows if r[0]])}
