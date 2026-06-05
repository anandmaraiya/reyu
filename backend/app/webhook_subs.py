"""Webhook event subscriptions.

Users can subscribe to specific event types.  Events are stored in Redis as
  webhook:subs:<user_id>  →  hash of event_type → json({url, created_at})

Supported event types:
  - PCR_THRESHOLD    : PCR crosses a configurable threshold
  - BIAS_CHANGE      : Market bias flips (bullish ↔ bearish)
  - OI_SPIKE         : Unusual OI buildup
  - ORDER_FILL       : Order executed
  - KILL_SWITCH      : Kill-switch triggered
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from app.store import store

log = logging.getLogger("reyu.webhook-subs")

SUB_KEY = "webhook:subs:{}"  # .format(user_id)

SUPPORTED_EVENTS = [
    "PCR_THRESHOLD",
    "BIAS_CHANGE",
    "OI_SPIKE",
    "ORDER_FILL",
    "KILL_SWITCH",
]


async def list_subs(user_id: str) -> dict[str, dict]:
    """Return {event_type: {url, created_at}} for a user."""
    raw = await store.r.hgetall(SUB_KEY.format(user_id))
    return {k: json.loads(v) for k, v in raw.items()}


async def add_sub(user_id: str, event_type: str, url: str) -> dict:
    """Subscribe a URL to an event type."""
    if event_type not in SUPPORTED_EVENTS:
        raise ValueError(f"Unsupported event type. Choose from: {', '.join(SUPPORTED_EVENTS)}")
    sub = {"url": url, "created_at": datetime.utcnow().isoformat()}
    await store.r.hset(SUB_KEY.format(user_id), event_type, json.dumps(sub))
    return sub


async def remove_sub(user_id: str, event_type: str) -> bool:
    """Unsubscribe from an event type. Returns True if it existed."""
    n = await store.r.hdel(SUB_KEY.format(user_id), event_type)
    return n > 0


async def emit_event(event_type: str, payload: dict) -> None:
    """Emit an event to all subscribers of that type.

    This is called by the scheduler / analytics engine when conditions are met.
    Each subscriber's URL receives a POST with the event payload.
    """
    import httpx

    # Scan all user subscription keys (in production you'd maintain an index)
    # For now we use a simpler approach: store a global index of event_type → user_ids
    index_key = f"webhook:index:{event_type}"
    user_ids = await store.r.smembers(index_key)

    if not user_ids:
        return

    async with httpx.AsyncClient(timeout=5) as c:
        for uid in user_ids:
            sub_raw = await store.r.hget(SUB_KEY.format(uid), event_type)
            if not sub_raw:
                continue
            sub = json.loads(sub_raw)
            url = sub.get("url", "")
            if not url:
                continue
            body = {
                "event": event_type,
                "timestamp": datetime.utcnow().isoformat(),
                "data": payload,
            }
            try:
                # Format for Discord/Telegram if needed
                if "discord" in url:
                    await c.post(url, json={"content": f"**[Reyu.ai] {event_type}**\n```json\n{json.dumps(payload, indent=2)}\n```"})
                elif "telegram" in url:
                    await c.post(url, json={"text": f"[Reyu.ai] {event_type}\n{json.dumps(payload, indent=2)}"})
                else:
                    await c.post(url, json=body)
            except Exception as e:
                log.warning("webhook event %s → %s failed: %s", event_type, url, e)


async def add_to_index(user_id: str, event_type: str) -> None:
    """Add a user to the event type index."""
    await store.r.sadd(f"webhook:index:{event_type}", user_id)


async def remove_from_index(user_id: str, event_type: str) -> None:
    """Remove a user from the event type index."""
    await store.r.srem(f"webhook:index:{event_type}", user_id)
