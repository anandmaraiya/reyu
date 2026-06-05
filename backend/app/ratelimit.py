"""Rate limiting for API key consumers.

Tier-based daily quotas enforced via Redis counters:
  - free : 100 requests / day
  - pro  : 10 000 requests / day
  - algo : unlimited (no counter)

Keys in Redis:  ratelimit:<key_id>:<YYYY-MM-DD>
TTL: 48 h (covers the day boundary comfortably).
"""
from __future__ import annotations

import logging
from datetime import date

from app.store import store

log = logging.getLogger("reyu.ratelimit")

# Requests per day per tier; 0 = unlimited
TIER_LIMITS: dict[str, int] = {
    "free": 100,
    "pro": 10_000,
    "algo": 0,       # 0 = unlimited
}

# How long Redis keys live (seconds) — 48 h so the key outlives the day
_TTL = 48 * 3600


def _today() -> str:
    return date.today().isoformat()


def _redis_key(key_id: str) -> str:
    return f"ratelimit:{key_id}:{_today()}"


async def check_rate_limit(key_id: str, tier: str) -> tuple[bool, int, int, int]:
    """Return (allowed, limit, remaining, reset_epoch).

    ``reset_epoch`` is midnight UTC of the next calendar day so clients
    know when the window rolls over.
    """
    limit = TIER_LIMITS.get(tier, 100)

    # Unlimited tier — still track usage for analytics but never block
    if limit == 0:
        rkey = _redis_key(key_id)
        pipe = store.r.pipeline()
        pipe.incr(rkey)
        pipe.expire(rkey, _TTL)
        results = await pipe.execute()
        used = results[0]
        return True, 0, 0, _next_midnight()

    rkey = _redis_key(key_id)
    pipe = store.r.pipeline()
    pipe.incr(rkey)
    pipe.expire(rkey, _TTL)
    results = await pipe.execute()
    used = results[0]

    remaining = max(0, limit - used)
    allowed = used <= limit
    reset_at = _next_midnight()

    if not allowed:
        log.warning("rate limit exceeded for key %s (%s tier): %d/%d", key_id, tier, used, limit)

    return allowed, limit, remaining, reset_at


async def get_usage(key_id: str, tier: str) -> dict:
    """Return current-day usage stats for an API key (for dashboard)."""
    limit = TIER_LIMITS.get(tier, 100)
    rkey = _redis_key(key_id)
    raw = await store.r.get(rkey)
    used = int(raw) if raw else 0
    return {
        "limit": limit,
        "used": used,
        "remaining": max(0, limit - used) if limit > 0 else -1,
        "reset_at": _next_midnight(),
    }


def _next_midnight() -> int:
    """Unix epoch of the next UTC midnight."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(nxt.timestamp())
