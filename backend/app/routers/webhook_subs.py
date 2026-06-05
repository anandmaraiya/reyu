"""Webhook event subscription management.

B2B users can subscribe to specific event types (PCR threshold, bias change, etc.)
and receive POST notifications at their webhook URL.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.routers.user_auth import require_auth, require_tier
from app.webhook_subs import (
    list_subs, add_sub, remove_sub,
    add_to_index, remove_from_index,
    SUPPORTED_EVENTS,
)

router = APIRouter()


class SubscribeRequest(BaseModel):
    event_type: str
    url: str


@router.get("/events")
async def list_supported_events():
    """List all supported event types."""
    return {"events": SUPPORTED_EVENTS}


@router.get("/subscriptions")
async def get_subscriptions(user: dict = Depends(require_tier("pro", "algo"))):
    """List the current user's event subscriptions."""
    subs = await list_subs(user["sub"])
    return {"subscriptions": [
        {"event_type": k, **v} for k, v in subs.items()
    ]}


@router.post("/subscriptions")
async def create_subscription(
    req: SubscribeRequest,
    user: dict = Depends(require_tier("pro", "algo")),
):
    """Subscribe to an event type. Requires pro or algo tier."""
    try:
        sub = await add_sub(user["sub"], req.event_type, req.url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await add_to_index(user["sub"], req.event_type)
    return {"ok": True, "event_type": req.event_type, **sub}


@router.delete("/subscriptions/{event_type}")
async def delete_subscription(
    event_type: str,
    user: dict = Depends(require_tier("pro", "algo")),
):
    """Unsubscribe from an event type."""
    existed = await remove_sub(user["sub"], event_type)
    if existed:
        await remove_from_index(user["sub"], event_type)
    return {"ok": True, "removed": existed}
