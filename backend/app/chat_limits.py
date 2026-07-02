"""Chat usage limits per tier — messages + LLM tokens.

Tracked in Redis with daily counters that auto-expire at midnight UTC
next day. Two counters per user per day:
    chat:msg:{user_key}:{yyyy-mm-dd}     — count of chat messages
    chat:tok:{user_key}:{yyyy-mm-dd}     — sum of input + output tokens

user_key = user_id for authed users, "anon:<ip_hash>" for anonymous.

Limits are enforced BEFORE the LLM call (fast fail) and tokens are
recorded AFTER (from the LLM provider's usage payload). If a user
crosses the token quota mid-response, they're marked over for the
rest of the day; subsequent messages get blocked.

Tier config lives in TIER_LIMITS below — edit there to adjust.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class TierLimit:
    daily_messages: int         # -1 = unlimited
    daily_tokens: int           # -1 = unlimited


# Free = trial gets full daily allowance. Anonymous gets the smallest.
TIER_LIMITS: dict[str, TierLimit] = {
    "anonymous": TierLimit(daily_messages=5,     daily_tokens=5_000),
    "free":      TierLimit(daily_messages=25,    daily_tokens=25_000),
    "pro":       TierLimit(daily_messages=500,   daily_tokens=500_000),
    "algo":      TierLimit(daily_messages=-1,    daily_tokens=5_000_000),
    "superadmin":TierLimit(daily_messages=-1,    daily_tokens=-1),
}


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _user_key(user_id: Optional[str], ip: Optional[str] = None) -> str:
    if user_id:
        return user_id
    if ip:
        # Hash IP so we don't store raw client IPs in Redis TTL keys long-term
        h = hashlib.sha256(ip.encode()).hexdigest()[:16]
        return f"anon:{h}"
    return "anon:unknown"


def _tier_key(tier: str, is_superadmin: bool = False) -> str:
    if is_superadmin:
        return "superadmin"
    t = (tier or "anonymous").lower()
    return t if t in TIER_LIMITS else "anonymous"


def _tier_key_from_email(email: Optional[str], tier: str) -> str:
    """Superadmin email always gets unlimited regardless of tier."""
    if email and email in {"algo@reyu.ai"}:
        return "superadmin"
    return _tier_key(tier)


async def get_usage(user_id: Optional[str], ip: Optional[str] = None) -> dict:
    """Return today's usage for the given user."""
    from app.store import store
    day = _today_utc()
    ukey = _user_key(user_id, ip)
    msg_raw = await store.r.get(f"chat:msg:{ukey}:{day}")
    tok_raw = await store.r.get(f"chat:tok:{ukey}:{day}")
    return {
        "date": day,
        "messages": int(msg_raw or 0),
        "tokens": int(tok_raw or 0),
    }


async def check_limits(
    tier: str,
    email: Optional[str],
    user_id: Optional[str],
    ip: Optional[str] = None,
) -> dict:
    """Called BEFORE an LLM call. Returns {allowed, tier, limit, used, reason}.
    Does not increment — the caller records usage after the LLM completes."""
    tkey = _tier_key_from_email(email, tier)
    limit = TIER_LIMITS[tkey]
    usage = await get_usage(user_id, ip)

    # Message-count gate
    if limit.daily_messages != -1 and usage["messages"] >= limit.daily_messages:
        return {
            "allowed": False,
            "tier": tkey,
            "limit_type": "messages",
            "limit": limit.daily_messages,
            "used": usage["messages"],
            "reason": f"Daily message limit reached ({limit.daily_messages}). Upgrade to Pro for 500/day or Algo for unlimited.",
            "resets_at": _reset_at_iso(),
        }

    # Token-count gate
    if limit.daily_tokens != -1 and usage["tokens"] >= limit.daily_tokens:
        return {
            "allowed": False,
            "tier": tkey,
            "limit_type": "tokens",
            "limit": limit.daily_tokens,
            "used": usage["tokens"],
            "reason": f"Daily token budget spent ({limit.daily_tokens:,} tokens). Upgrade to expand.",
            "resets_at": _reset_at_iso(),
        }

    return {
        "allowed": True,
        "tier": tkey,
        "limits": {"messages": limit.daily_messages, "tokens": limit.daily_tokens},
        "used": usage,
    }


async def record_usage(
    user_id: Optional[str],
    ip: Optional[str],
    tokens: int = 0,
) -> None:
    """Called AFTER an LLM call. Increments message count by 1 and
    tokens by the reported usage. Keys auto-expire 48h out (safety margin
    over midnight-UTC rollover)."""
    from app.store import store
    day = _today_utc()
    ukey = _user_key(user_id, ip)
    TTL = 60 * 60 * 48  # 48h
    async with store.r.pipeline(transaction=False) as pipe:
        await pipe.incr(f"chat:msg:{ukey}:{day}")
        await pipe.expire(f"chat:msg:{ukey}:{day}", TTL)
        if tokens > 0:
            await pipe.incrby(f"chat:tok:{ukey}:{day}", tokens)
            await pipe.expire(f"chat:tok:{ukey}:{day}", TTL)
        await pipe.execute()


def _reset_at_iso() -> str:
    """Next UTC midnight."""
    now = datetime.now(timezone.utc)
    tomorrow = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    from datetime import timedelta
    return (tomorrow + timedelta(days=1)).isoformat()
