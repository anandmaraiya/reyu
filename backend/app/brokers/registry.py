"""Broker registry — maps broker_id → class, and manages per-user instances.

Usage:
    from app.brokers.registry import get_broker, BROKER_CATALOG

    # Get a broker instance for a user (cached in Redis)
    broker = await get_broker(user_id="abc", broker_id="fyers")

    # List available brokers for the UI
    catalog = BROKER_CATALOG   # [{id, name, logo, status, auth_type}]
"""
from __future__ import annotations

import json
from typing import Type

from app.brokers.base import BrokerClient
from app.brokers.fyers import FyersBroker
from app.brokers.zerodha import ZerodhaBroker
from app.brokers.angelone import AngelOneBroker


# ─── Registry ────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, Type[BrokerClient]] = {
    "fyers":    FyersBroker,
    "zerodha":  ZerodhaBroker,
    "angelone": AngelOneBroker,
}

# UI catalog — what gets shown on the broker connect screen
BROKER_CATALOG = [
    {
        "id":        "fyers",
        "name":      "Fyers",
        "status":    "live",          # live | beta | coming_soon
        "auth_type": "oauth",         # oauth | totp | api_key
        "features":  ["options", "futures", "equity", "data"],
        "logo_url":  "/static/brokers/fyers.svg",
    },
    {
        "id":        "zerodha",
        "name":      "Zerodha",
        "status":    "beta",
        "auth_type": "oauth",
        "features":  ["options", "futures", "equity"],
        "logo_url":  "/static/brokers/zerodha.svg",
    },
    {
        "id":        "angelone",
        "name":      "AngelOne",
        "status":    "coming_soon",
        "auth_type": "totp",
        "features":  ["options", "futures", "equity"],
        "logo_url":  "/static/brokers/angelone.svg",
    },
    {
        "id":        "groww",
        "name":      "Groww",
        "status":    "coming_soon",
        "auth_type": "oauth",
        "features":  ["equity"],
        "logo_url":  "/static/brokers/groww.svg",
    },
]


# ─── Instance factory ─────────────────────────────────────────────────────────

def make_broker(broker_id: str, access_token: str | None = None) -> BrokerClient:
    """Create a broker instance. Raises ValueError for unknown broker_id."""
    cls = _REGISTRY.get(broker_id)
    if not cls:
        raise ValueError(f"Unknown broker: {broker_id!r}. Available: {list(_REGISTRY)}")
    return cls(access_token=access_token)


async def get_broker(user_id: str, broker_id: str) -> BrokerClient:
    """Get a broker instance for a user, loading the access token from Redis."""
    from app.store import store
    token_key = f"broker_token:{user_id}:{broker_id}"
    token = await store.r.get(token_key)
    if isinstance(token, bytes):
        token = token.decode()
    return make_broker(broker_id, access_token=token or None)


async def save_broker_token(user_id: str, broker_id: str, token_data: dict, ttl: int = 86400):
    """Persist a broker token to Redis. ttl defaults to 24h (Fyers daily expiry)."""
    from app.store import store
    token_key = f"broker_token:{user_id}:{broker_id}"
    meta_key  = f"broker_meta:{user_id}:{broker_id}"
    await store.r.set(token_key, token_data.get("access_token", ""), ex=ttl)
    await store.r.set(meta_key, json.dumps({
        "broker_id":   broker_id,
        "connected_at": token_data.get("connected_at", ""),
        "expires_at":   token_data.get("expires_at", ""),
    }), ex=ttl)


async def get_user_brokers(user_id: str) -> list[dict]:
    """Return list of brokers the user currently has tokens for."""
    from app.store import store
    connected = []
    for broker_id in _REGISTRY:
        meta_key = f"broker_meta:{user_id}:{broker_id}"
        raw = await store.r.get(meta_key)
        if raw:
            meta = json.loads(raw)
            meta["status"] = "connected"
            connected.append(meta)
    return connected


async def disconnect_broker(user_id: str, broker_id: str):
    """Remove broker tokens from Redis."""
    from app.store import store
    await store.r.delete(f"broker_token:{user_id}:{broker_id}")
    await store.r.delete(f"broker_meta:{user_id}:{broker_id}")
