"""Fyers OAuth login flow.

1. GET /api/auth/login         -> returns Fyers login URL
2. User logs in on Fyers; redirected to /api/auth/callback?auth_code=...
3. Callback exchanges auth_code for access_token and persists it in Redis.

Headless / VM mode:
  POST /api/auth/set-token      -> inject a pre-obtained Fyers access token
                                   (for Linux servers where no browser is available)
"""
import os
import secrets
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from fyers_apiv3 import fyersModel

from app.config import settings
from app.fyers import client as fy

router = APIRouter()


class SetTokenRequest(BaseModel):
    access_token: str
    # Optional: simple shared secret to protect this endpoint on Linux VMs.
    # Set REYU_TOKEN_SECRET in your .env to require it.
    secret: str = ""


def _session(state: str | None = None) -> fyersModel.SessionModel:
    s = fyersModel.SessionModel(
        client_id=settings.fyers_app_id,
        secret_key=settings.fyers_secret_key,
        redirect_uri=settings.fyers_redirect_uri,
        response_type="code",
        grant_type="authorization_code",
    )
    if state:
        # Set state on the SDK instance — without it, the SDK appends
        # `state=None` (Python literal) and Fyers' Cloudflare WAF returns
        # 403 Forbidden on the resulting URL.
        try:
            s.state = state
        except Exception:
            pass
    return s


@router.get("/login")
async def login():
    # Generate a CSRF-style state token. Without a real state value the
    # Fyers SDK injects literal "None" into the URL → Cloudflare flags as
    # bot traffic and returns 403, which manifests in the UI as the
    # "re-authenticate" button silently doing nothing.
    state = secrets.token_urlsafe(16)
    url = _session(state=state).generate_authcode()
    # Belt-and-suspenders: if the SDK still rendered "state=None", replace
    # with the real token instead of stripping (so the param IS present).
    if url and "state=None" in url:
        url = url.replace("state=None", f"state={state}")
    elif url and "state=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}state={state}"
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
    # FRONTEND_URL may be set in .env for VM deployments (e.g. http://35.202.153.147).
    # Falls back to "/" which works for same-origin nginx deployments.
    frontend_url = os.environ.get("FRONTEND_URL", "")
    redirect_to = f"{frontend_url}/?fyers=ok" if frontend_url else "/?fyers=ok"
    return RedirectResponse(redirect_to)


@router.get("/status")
async def status():
    token = await fy.get_access_token()
    return {"authenticated": bool(token)}


@router.post("/logout")
async def logout():
    await fy.store.r.delete(fy.TOKEN_KEY)
    return {"ok": True}


@router.post("/set-token")
async def set_token(req: SetTokenRequest):
    """Headless token injection for Linux VM / CI environments where a browser
    is not available.

    Usage:
      1. Obtain a Fyers access token on any browser machine via /api/auth/login
      2. POST it here: curl -X POST http://<vm>:8000/api/auth/set-token \\
             -H 'Content-Type: application/json' \\
             -d '{"access_token":"<token>","secret":"<REYU_TOKEN_SECRET>"}'
      3. The token is stored in Redis with a 24h TTL (Fyers tokens expire daily).

    Set REYU_TOKEN_SECRET in your .env to require a shared secret.
    Leave it blank only on private/firewalled machines.
    """
    expected_secret = os.environ.get("REYU_TOKEN_SECRET", "")
    if expected_secret and req.secret != expected_secret:
        raise HTTPException(403, "Invalid secret")
    if not req.access_token.strip():
        raise HTTPException(400, "access_token is required")
    await fy.set_access_token(req.access_token.strip())
    return {"ok": True, "message": "Fyers access token updated in Redis (24h TTL)"}
