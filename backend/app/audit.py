"""Audit trail helper (F-A9).

Fire-and-forget writes to the `audit_log` table. NEVER fails the
originating request — if the DB insert errors, we log and swallow.
The originating action (order, login, subscription change) should
never be blocked by an audit-write hiccup.

Usage:
    from app.audit import record

    await record(
        event_type="ORDER_EXIT",
        actor_id=user_id,
        actor_email=user_email,
        resource_type="order",
        resource_id=order_id,
        action=f"Exited {leg_symbol} @ market",
        meta={"symbol": leg_symbol, "qty": qty, "mode": "LIVE"},
        request=request,   # optional FastAPI Request for IP/UA capture
    )

Event-type conventions (extend as new money paths land):
    LOGIN / LOGIN_FAILED / REGISTER / PASSWORD_RESET
    ONBOARDED
    BROKER_CONNECT / BROKER_DISCONNECT
    STRATEGY_CREATE / STRATEGY_PROMOTE / STRATEGY_HALT / STRATEGY_DELETE
    ORDER_EXIT / ORDER_EXECUTE
    CHAT_TURN (prompt + AI response, for compliance retention)
    LEGAL_ACCEPT (versioned acceptance of a legal/compliance document)
    SUBSCRIPTION_UPGRADE / SUBSCRIPTION_CANCEL
    SUPERADMIN_ACTION (for anything algo@reyu.ai does that affects data)
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import Request

from app.db import SessionLocal, AuditLog

log = logging.getLogger("reyu.audit")


async def record(
    event_type: str,
    *,
    actor_id: Optional[str] = None,
    actor_email: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    action: Optional[str] = None,
    meta: Optional[dict] = None,
    request: Optional[Request] = None,
) -> None:
    """Write an audit-log row. Never raises."""
    try:
        ip = None
        ua = None
        if request:
            # Trust the first entry in X-Forwarded-For only if Caddy set it
            # (public IPs on VM). Fall back to the direct client if no proxy.
            xff = request.headers.get("x-forwarded-for")
            ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else None)
            ua = request.headers.get("user-agent")

        row = AuditLog(
            event_type=event_type,
            actor_id=actor_id,
            actor_email=actor_email,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            meta=json.dumps(meta) if meta else None,
            ip_address=ip,
            user_agent=ua[:500] if ua else None,      # cap UA at 500 chars — enough for forensics
        )
        async with SessionLocal() as s:
            s.add(row)
            await s.commit()
    except Exception as e:
        log.warning("audit_write_failed event=%s actor=%s err=%s",
                    event_type, actor_email or actor_id, e)
