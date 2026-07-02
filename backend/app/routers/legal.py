"""Legal / compliance acceptance endpoints (F-A15).

Serves the versioned legal documents and records user acceptance. The
document registry lives in app.legal; acceptance rows in
user_legal_acceptance.

Endpoints:
    GET  /api/legal/docs                 — list all docs + current versions (public)
    GET  /api/legal/docs/{doc_type}      — full text of one doc (public)
    GET  /api/legal/status               — my acceptance status + what's pending (auth)
    POST /api/legal/accept               — accept one or more docs (auth)

Gating helper:
    require_acceptance(user_id, doc_types)  — raises 451 with a structured
        payload listing which docs are outstanding. Used to block LIVE
        deployment until execution authorization (+ platform docs) accepted.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

from app.db import SessionLocal, UserLegalAcceptance
from app.legal import (
    LEGAL_DOCS, PLATFORM_DOCS, LIVE_DOCS, current_version, doc_meta,
)
from app.routers.user_auth import require_user

router = APIRouter(prefix="/api/legal", tags=["legal"])


# ── Public: document registry ───────────────────────────────────────
@router.get("/docs")
async def list_docs():
    """All legal documents with current versions and gating groups.
    Public so users can read before signing up."""
    return {
        "docs": [doc_meta(dt) for dt in LEGAL_DOCS],
        "platform_docs": PLATFORM_DOCS,   # required to use the platform
        "live_docs": LIVE_DOCS,           # required before LIVE deployment
    }


@router.get("/docs/{doc_type}")
async def get_doc(doc_type: str):
    """Full text (markdown) of a single legal document."""
    d = LEGAL_DOCS.get(doc_type)
    if not d:
        raise HTTPException(404, f"Unknown document: {doc_type}")
    return dict(d)


# ── Acceptance status ───────────────────────────────────────────────
async def _accepted_versions(user_id: str) -> dict[str, int]:
    """Map doc_type -> highest accepted version for this user."""
    async with SessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT doc_type, MAX(version) AS v
            FROM user_legal_acceptance
            WHERE user_id = :uid
            GROUP BY doc_type
        """), {"uid": user_id})).fetchall()
    return {r.doc_type: int(r.v) for r in rows}


def _pending(accepted: dict[str, int], doc_types: list[str]) -> list[str]:
    """Docs in doc_types not yet accepted at their current version."""
    out = []
    for dt in doc_types:
        if accepted.get(dt, -1) < current_version(dt):
            out.append(dt)
    return out


@router.get("/status")
async def status(user: dict = Depends(require_user)):
    accepted = await _accepted_versions(user["sub"])
    platform_pending = _pending(accepted, PLATFORM_DOCS)
    live_pending = _pending(accepted, PLATFORM_DOCS + LIVE_DOCS)
    return {
        "accepted": [
            {"doc_type": dt, "version": v, "current": current_version(dt),
             "up_to_date": v >= current_version(dt)}
            for dt, v in accepted.items() if dt in LEGAL_DOCS
        ],
        "platform_pending": [doc_meta(dt) for dt in platform_pending],
        "live_pending": [doc_meta(dt) for dt in live_pending],
        "platform_ok": len(platform_pending) == 0,
        "live_ok": len(live_pending) == 0,
    }


# ── Accept ──────────────────────────────────────────────────────────
class AcceptItem(BaseModel):
    doc_type: str
    version: int


class AcceptRequest(BaseModel):
    accept: list[AcceptItem]


@router.post("/accept")
async def accept(req: AcceptRequest, request: Request,
                 user: dict = Depends(require_user)):
    """Record acceptance of one or more legal documents. Version must
    match the current version of each doc (prevents accepting stale text)."""
    if not req.accept:
        raise HTTPException(400, "No documents to accept")

    xff = request.headers.get("x-forwarded-for")
    ip = xff.split(",")[0].strip() if xff else (
        request.client.host if request.client else None)
    ua = request.headers.get("user-agent")

    recorded = []
    async with SessionLocal() as s:
        for item in req.accept:
            if item.doc_type not in LEGAL_DOCS:
                raise HTTPException(400, f"Unknown document: {item.doc_type}")
            cur = current_version(item.doc_type)
            if item.version != cur:
                raise HTTPException(409,
                    f"{item.doc_type} is at version {cur}; you sent {item.version}. "
                    "Reload the document and accept the current version.")
            s.add(UserLegalAcceptance(
                id=str(uuid.uuid4()),
                user_id=user["sub"],
                doc_type=item.doc_type,
                version=item.version,
                accepted_at=datetime.utcnow(),
                ip_address=ip,
                user_agent=ua[:500] if ua else None,
            ))
            recorded.append({"doc_type": item.doc_type, "version": item.version})
        await s.commit()

    # Audit each acceptance for the compliance trail.
    from app.audit import record as _audit
    for r in recorded:
        await _audit(
            event_type="LEGAL_ACCEPT",
            actor_id=user["sub"], actor_email=user.get("email"),
            resource_type="legal_doc", resource_id=r["doc_type"],
            action=f"Accepted {r['doc_type']} v{r['version']}",
            meta=r, request=request,
        )

    return {"ok": True, "recorded": recorded}


# ── Gating helper (importable) ──────────────────────────────────────
async def require_acceptance(user_id: str, doc_types: list[str]) -> None:
    """Raise HTTP 451 with a structured payload if any of `doc_types`
    is not accepted at its current version. Call before LIVE deployment.
    """
    accepted = await _accepted_versions(user_id)
    pending = _pending(accepted, doc_types)
    if pending:
        raise HTTPException(451, {
            "message": "Legal acceptance required before this action.",
            "legal_pending": [doc_meta(dt) for dt in pending],
        })
