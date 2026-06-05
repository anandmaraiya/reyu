"""Fyers OAuth login flow.

1. GET /api/auth/login         -> returns Fyers login URL
2. User logs in on Fyers; redirected to /api/auth/callback?auth_code=...
3. Callback exchanges auth_code for access_token and persists it in Redis.
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.concurrency import run_in_threadpool
from fyers_apiv3 import fyersModel

from app.config import settings
from app.fyers import client as fy

router = APIRouter()


def _session() -> fyersModel.SessionModel:
    return fyersModel.SessionModel(
        client_id=settings.fyers_app_id,
        secret_key=settings.fyers_secret_key,
        redirect_uri=settings.fyers_redirect_uri,
        response_type="code",
        grant_type="authorization_code",
    )


@router.get("/login")
async def login():
    url = _session().generate_authcode()
    # The Fyers SDK appends `state=None` (Python literal) when no state was
    # provided — strip it before handing the URL to the browser so the OAuth
    # round-trip stays clean.
    if url and "state=None" in url:
        url = url.replace("&state=None", "").replace("?state=None&", "?").replace("?state=None", "")
    return {"login_url": url}


@router.get("/callback")
async def callback(auth_code: str = Query(...), state: str | None = None):
    s = _session()
    s.set_token(auth_code)
    resp = await run_in_threadpool(s.generate_token)
    token = resp.get("access_token")
    if not token:
        raise HTTPException(400, f"Fyers token exchange failed: {resp}")
    await fy.set_access_token(token)
    return RedirectResponse("http://localhost:5173/?login=ok")


@router.get("/status")
async def status():
    token = await fy.get_access_token()
    return {"authenticated": bool(token)}


@router.post("/logout")
async def logout():
    await fy.store.r.delete(fy.TOKEN_KEY)
    return {"ok": True}
