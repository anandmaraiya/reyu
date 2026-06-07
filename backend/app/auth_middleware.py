"""Global auth middleware — protects all /api/* routes.

Public paths (no auth required):
  - /api/health
  - /api/auth/*          (Fyers OAuth flow)
  - /api/user/register   (account creation)
  - /api/user/login      (login)
  - /api/user/refresh    (token refresh)
  - /api/stream/ws/*     (WebSocket — auth checked separately)

All other /api/* routes require a valid JWT or X-API-Key.

When an X-API-Key is used, the middleware checks rate limits and injects
X-RateLimit-* response headers.
"""
from __future__ import annotations

import re
import time
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.routers.user_auth import _user_from_api_key, _decode_token
from app.ratelimit import check_rate_limit

# Paths that are publicly accessible (no JWT required)
_PUBLIC_PATHS = [
    re.compile(r"^/api/health$"),
    re.compile(r"^/api/auth/"),            # Fyers OAuth
    re.compile(r"^/api/user/register$"),
    re.compile(r"^/api/user/login$"),
    re.compile(r"^/api/user/refresh$"),
    re.compile(r"^/api/stream/ws/"),       # WebSocket
    re.compile(r"^/ws/"),                  # WebSocket (without /api prefix)
    re.compile(r"^/api/chat"),             # chat endpoint (auth handled per-route)
    re.compile(r"^/api/chart/"),           # chart PNGs (embed in chat / Telegram / Discord)
    re.compile(r"^/api/telegram/webhook$"), # Telegram → us (no auth header from TG)
    re.compile(r"^/api/system/status$"),   # health probe used by sidebar
    re.compile(r"^/api/options/"),         # read-only chain/quotes (free tier)
    re.compile(r"^/api/ts/"),              # read-only time-series
    re.compile(r"^/api/backtest/"),        # historical replay (read-only)
    re.compile(r"^/api/rl/"),              # RL trading engine (paper trades, read-only inspection)
    re.compile(r"^/api/data/snapshot-health"),  # pipeline health probe (no PII)
    re.compile(r"^/api/data/bhavcopy/"),         # historical EOD ingest (admin-ish, fine)
    re.compile(r"^/api/backtest-eod/"),          # EOD Bhavcopy validation harness
    # NOTE: /api/strategies stays behind auth — strategies are user-owned.
]

# Paths that B2B API key consumers hit — rate limit these when using API key
_RATE_LIMITED_PATHS = [
    re.compile(r"^/api/options/"),
    re.compile(r"^/api/ts/"),
    re.compile(r"^/api/data/"),
]


def _is_public(path: str) -> bool:
    return any(p.match(path) for p in _PUBLIC_PATHS)


def _is_rate_limited(path: str) -> bool:
    return any(p.match(path) for p in _RATE_LIMITED_PATHS)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Only intercept /api/* routes
        if not path.startswith("/api/"):
            return await call_next(request)

        # Allow public paths through
        if _is_public(path):
            return await call_next(request)

        # Try Bearer token first
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = _decode_token(token)
            if payload and payload.get("type") == "access":
                request.state.user = payload
                return await call_next(request)

        # Try X-API-Key
        api_key = request.headers.get("x-api-key")
        if api_key:
            user = await _user_from_api_key(api_key)
            if user:
                request.state.user = user

                # Rate limit check for API-key-authenticated requests on data paths
                if _is_rate_limited(path) and user.get("via") == "api_key":
                    key_id = user.get("key_id", "")
                    tier = user.get("tier", "free")
                    allowed, limit, remaining, reset_at = await check_rate_limit(key_id, tier)
                    if not allowed:
                        return JSONResponse(
                            status_code=429,
                            content={"detail": f"Rate limit exceeded — {tier} tier allows {limit} requests/day"},
                            headers={
                                "X-RateLimit-Limit": str(limit),
                                "X-RateLimit-Remaining": "0",
                                "X-RateLimit-Reset": str(reset_at),
                                "Retry-After": str(reset_at - int(time.time())),
                            },
                        )
                    # Proceed with rate limit headers
                    resp = await call_next(request)
                    resp.headers["X-RateLimit-Limit"] = str(limit)
                    resp.headers["X-RateLimit-Remaining"] = str(remaining)
                    resp.headers["X-RateLimit-Reset"] = str(reset_at)
                    return resp

                return await call_next(request)

        # No valid credentials
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required — provide a Bearer token or X-API-Key header"},
        )
