"""B2B data API — dedicated endpoints for API-key-authenticated consumers.

All routes under /api/data/* require a valid X-API-Key and enforce
tier-based rate limits.  Responses include X-RateLimit-* headers.

Endpoints mirror the existing /api/options/* and /api/ts/* read-only
surfaces so B2B consumers have a clean, stable contract.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.routers.user_auth import require_auth
from app.ratelimit import check_rate_limit, get_usage

log = logging.getLogger("reyu.data-api")
router = APIRouter()


# ── helpers ─────────────────────────────────────────────────

async def _check_api_rate_limit(request: Request) -> None:
    """Dependency: enforce rate limit when the caller used an API key.
    Returns a 429 response dict if over limit, or None if allowed."""
    user = getattr(request.state, "user", None)
    if user and user.get("via") == "api_key":
        key_id = user.get("key_id", "")
        tier = user.get("tier", "free")
        allowed, limit, remaining, reset_at = await check_rate_limit(key_id, tier)
        # Store on request state so we can add headers in the endpoint
        request.state.rate_limit_limit = limit
        request.state.rate_limit_remaining = remaining
        request.state.rate_limit_reset = reset_at
        if not allowed:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded — {tier} tier allows {limit} requests/day"},
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_at),
                },
            )
    return None


def _add_rate_headers(response, request: Request) -> None:
    """Inject X-RateLimit-* headers if rate limit was evaluated."""
    for hdr in ("rate_limit_limit", "rate_limit_remaining", "rate_limit_reset"):
        val = getattr(request.state, hdr, None)
        if val is not None:
            header_name = "X-" + hdr.replace("rate_limit_", "RateLimit-").title().replace("-", "-")
            # Fix casing: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset
            header_name = hdr.replace("rate_limit_", "X-RateLimit-").replace("_limit", "Limit").replace("_remaining", "Remaining").replace("_reset", "Reset")
            response.headers[header_name] = str(val)


# ── Pydantic models ─────────────────────────────────────────

class ChainResponse(BaseModel):
    underlying: str
    ltp: float | None = None
    expiry: str | None = None
    expiries: list[dict] = []
    strikes: list[dict] = []
    summary: dict = {}
    bias: dict = {}


class QuotesResponse(BaseModel):
    quotes: list[dict] = []


# ── Routes ──────────────────────────────────────────────────

@router.get("/chain")
async def data_chain(
    request: Request,
    symbol: str = Query(..., description="Underlying symbol, e.g. NSE:NIFTY50-INDEX"),
    strikecount: int = Query(25, ge=1, le=100),
    expiry: str = Query("", description="Optional expiry filter"),
    user: dict = Depends(require_auth),
):
    """Option chain for a symbol — same data as /api/options/chain but
    requires API key auth and enforces rate limits."""
    rate_resp = await _check_api_rate_limit(request)
    if rate_resp:
        return rate_resp

    from app.fyers import client as fy
    from app.analytics.chain import normalize_chain, trade_bias

    raw = await fy.option_chain(symbol, strikecount, timestamp=expiry)
    chain = normalize_chain(raw)
    chain["bias"] = trade_bias(chain["summary"])

    from fastapi.responses import JSONResponse
    resp = JSONResponse(content=chain)
    _add_rate_headers(resp, request)
    return resp


@router.get("/quotes")
async def data_quotes(
    request: Request,
    symbols: str = Query(..., description="Comma-separated symbols"),
    user: dict = Depends(require_auth),
):
    """Live quotes for one or more symbols."""
    rate_resp = await _check_api_rate_limit(request)
    if rate_resp:
        return rate_resp

    from app.fyers import client as fy
    result = await fy.quotes(symbols.split(","))

    from fastapi.responses import JSONResponse
    resp = JSONResponse(content=result)
    _add_rate_headers(resp, request)
    return resp


@router.get("/snapshots")
async def data_snapshots(
    request: Request,
    symbol: str = Query(...),
    interval: Literal["1m", "5m", "15m"] = "1m",
    minutes: int = Query(240, ge=1, le=2880),
    user: dict = Depends(require_auth),
):
    """Option-chain snapshot time-series (PCR, OI, max-pain, bias)."""
    rate_resp = await _check_api_rate_limit(request)
    if rate_resp:
        return rate_resp

    from app.routers import timeseries
    result = await timeseries.snapshots(
        symbol=symbol, interval=interval, minutes=minutes,
        today_only=True, s=__import__("app.db", fromlist=["SessionLocal"]).SessionLocal(),
    )

    from fastapi.responses import JSONResponse
    resp = JSONResponse(content=result)
    _add_rate_headers(resp, request)
    return resp


@router.get("/usage")
async def data_usage(
    request: Request,
    user: dict = Depends(require_auth),
):
    """Return today's API usage for the calling key."""
    if user.get("via") != "api_key":
        return {"detail": "This endpoint is only available for API-key-authenticated requests"}

    key_id = user.get("key_id", "")
    tier = user.get("tier", "free")
    usage = await get_usage(key_id, tier)
    return {
        "key_id": key_id,
        "tier": tier,
        **usage,
    }
