"""Broker connect/disconnect router — broker-agnostic OAuth + token management.

Endpoints:
  GET  /api/brokers/catalog              list available brokers + status
  GET  /api/brokers/connected            user's connected brokers
  GET  /api/brokers/{id}/oauth-url       get OAuth redirect URL
  POST /api/brokers/{id}/callback        exchange auth code → token
  DELETE /api/brokers/{id}              disconnect
  GET  /api/brokers/{id}/profile         account profile from broker
  GET  /api/brokers/{id}/positions       live positions
  GET  /api/brokers/{id}/quotes          live quotes (query: symbols)
"""
from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel

from app.brokers.registry import (
    BROKER_CATALOG, get_broker, make_broker,
    save_broker_token, get_user_brokers, disconnect_broker,
)
from app.config import settings

router = APIRouter(prefix="/api/brokers", tags=["brokers"])


# ─── Public ───────────────────────────────────────────────────────────────────

@router.get("/catalog")
async def catalog():
    """All brokers Reyu supports — used by the broker-connect UI."""
    return {"brokers": BROKER_CATALOG}


# ─── Auth-required ────────────────────────────────────────────────────────────

@router.get("/connected")
async def connected_brokers(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        return {"brokers": []}
    return {"brokers": await get_user_brokers(user["sub"])}


@router.get("/{broker_id}/oauth-url")
async def oauth_url(broker_id: str, request: Request):
    """Return the OAuth login URL for a broker. No auth required — user hasn't connected yet."""
    redirect_uri = f"{settings.base_url}/api/brokers/{broker_id}/callback"
    try:
        broker = make_broker(broker_id)
        url = broker.oauth_url(redirect_uri=redirect_uri, state="")
        return {"url": url, "broker_id": broker_id}
    except ValueError as e:
        raise HTTPException(404, str(e))


class CallbackRequest(BaseModel):
    code: str
    state: str = ""


@router.post("/{broker_id}/callback")
async def broker_callback(broker_id: str, body: CallbackRequest, request: Request):
    """Exchange auth code for access token and save to Redis."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Sign in to connect a broker")

    redirect_uri = f"{settings.base_url}/api/brokers/{broker_id}/callback"
    try:
        broker = make_broker(broker_id)
        token_data = await broker.exchange_token(body.code, redirect_uri)
        await save_broker_token(user["sub"], broker_id, token_data)
        return {"status": "connected", "broker_id": broker_id}
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))


@router.delete("/{broker_id}")
async def disconnect(broker_id: str, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    await disconnect_broker(user["sub"], broker_id)
    return {"status": "disconnected", "broker_id": broker_id}


@router.get("/{broker_id}/profile")
async def profile(broker_id: str, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    broker = await get_broker(user["sub"], broker_id)
    p = await broker.get_profile()
    return {
        "user_id": p.user_id, "name": p.name, "email": p.email,
        "broker": p.broker,
        "funds_available": round(p.funds_available, 2),
        "funds_used": round(p.funds_used, 2),
        "connected": broker.is_connected,
    }


@router.get("/{broker_id}/positions")
async def positions(broker_id: str, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, {"message": "Connect Fyers to see your positions.", "gate": "login"})
    broker = await get_broker(user["sub"], broker_id)
    pos = await broker.get_positions()
    return {
        "positions": [
            {
                "symbol": p.symbol, "qty": p.qty, "avg_price": round(p.avg_price, 2),
                "ltp": round(p.ltp, 2), "pnl": round(p.pnl, 2),
                "pnl_pct": round(p.pnl_pct, 2), "side": p.side,
            }
            for p in pos
        ],
        "connected": broker.is_connected,
    }


@router.get("/{broker_id}/quotes")
async def quotes(
    broker_id: str,
    request: Request,
    symbols: str = Query(..., description="Comma-separated symbols, e.g. NSE:NIFTY50-INDEX"),
):
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    # Quotes are public for anonymous users (demo mode)
    user = getattr(request.state, "user", None)
    user_id = user["sub"] if user else "anonymous"
    broker = await get_broker(user_id, broker_id)
    qs = await broker.get_quotes(sym_list)
    return {
        "quotes": [
            {"symbol": q.symbol, "ltp": round(q.ltp, 2), "open": round(q.open, 2),
             "high": round(q.high, 2), "low": round(q.low, 2), "close": round(q.close, 2),
             "volume": q.volume, "oi": q.oi}
            for q in qs
        ],
        "demo": not broker.is_connected,
    }


@router.get("/{broker_id}/option-chain")
async def option_chain(broker_id: str, request: Request, underlying: str = Query(...)):
    """Option chain — available to anonymous users in demo mode."""
    user = getattr(request.state, "user", None)
    user_id = user["sub"] if user else "anonymous"
    broker = await get_broker(user_id, broker_id)
    chain = await broker.get_option_chain(underlying)
    return {
        "underlying": chain.underlying,
        "spot": round(chain.spot, 2),
        "atm_strike": chain.atm_strike,
        "fetched_at": chain.fetched_at.isoformat(),
        "demo": not broker.is_connected,
        "legs": [
            {
                "strike": l.strike, "expiry": l.expiry.isoformat(),
                "option_type": l.option_type, "ltp": round(l.ltp, 2),
                "oi": l.oi, "oi_change": l.oi_change, "iv": round(l.iv, 2),
                "delta": round(l.delta, 4),
            }
            for l in chain.legs
        ],
    }
