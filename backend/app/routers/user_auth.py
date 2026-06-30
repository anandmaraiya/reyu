"""User auth: register, login, JWT issuance, refresh, logout.

JWTs are short-lived (30 min access / 7 day refresh). Tokens carry
{sub, email, tier} so the middleware can enforce gating without a DB hit.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, User, ApiKey

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
auth_scheme = HTTPBearer(auto_error=False)

# -- JWT helpers --------------------------------

ALGORITHM = "HS256"
ACCESS_EXPIRE_MIN = 30          # minutes
REFRESH_EXPIRE_DAYS = 7


def _create_token(data: dict, expires_delta: timedelta) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + expires_delta
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=ALGORITHM)


def _decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        return None


def create_access_token(user: User) -> str:
    return _create_token(
        {"sub": user.id, "email": user.email, "tier": user.tier, "type": "access"},
        timedelta(minutes=ACCESS_EXPIRE_MIN),
    )


def create_refresh_token(user: User) -> str:
    return _create_token(
        {"sub": user.id, "type": "refresh"},
        timedelta(days=REFRESH_EXPIRE_DAYS),
    )


# -- Pydantic models ----------------------------

class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class UserProfile(BaseModel):
    id: str
    email: str
    display_name: str
    tier: str
    created_at: str


class TierUpdateRequest(BaseModel):
    tier: str  # free | pro | algo


# -- Dependency: current user -------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(auth_scheme),
) -> Optional[dict]:
    """Extract user from JWT. Returns None if no/invalid token."""
    if not credentials:
        return None
    payload = _decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        return None
    return payload


async def require_user(
    credentials: HTTPAuthorizationCredentials = Depends(auth_scheme),
) -> dict:
    """Like get_current_user but raises 401 if missing."""
    user = await get_current_user(credentials)
    if not user:
        raise HTTPException(401, "Authentication required")
    return user


# Superadmin = the singular operator account that can run pipeline
# diagnostics + see the dataset-fills dashboard. Hardcoded by email
# rather than a DB flag so it survives DB resets and is obvious in code.
SUPERADMIN_EMAILS = {"algo@reyu.ai"}


async def require_superadmin(user: dict = Depends(require_user)) -> dict:
    """Gate for operator-only endpoints (pipeline diagnostics, daily-
    fills dashboard, scheduled-job triggers)."""
    if user.get("email") not in SUPERADMIN_EMAILS:
        raise HTTPException(403, "Superadmin only")
    return user


def require_tier(*tiers: str):
    """Dependency factory: raise 403 if user's tier is not in the allowed set.
    For paid tiers (pro/algo), also verifies the subscription is active in the DB."""
    async def checker(user: dict = Depends(require_user)) -> dict:
        if not user:
            raise HTTPException(401, "Authentication required")
        user_tier = user.get("tier", "free")
        if user_tier not in tiers:
            raise HTTPException(403, f"Requires one of tiers: {', '.join(tiers)}")

        # For paid tiers, verify subscription is actually active in DB
        if user_tier in ("pro", "algo"):
            async with SessionLocal() as s:
                result = await s.execute(select(User).where(User.id == user["sub"]))
                db_user = result.scalar_one_or_none()
                if not db_user:
                    raise HTTPException(401, "User not found")
                # Check subscription status
                if db_user.subscription_status not in ("active", None):
                    # None = legacy user who set tier manually (back-compat)
                    # If subscription is cancelled/expired/paused, deny access
                    if db_user.subscription_status in ("cancelled", "expired", "paused", "halted"):
                        raise HTTPException(
                            403,
                            f"Your {user_tier} subscription is {db_user.subscription_status}. "
                            "Please renew to access this feature."
                        )
                # Check if subscription has expired
                if db_user.subscription_ends_at and db_user.subscription_ends_at < datetime.utcnow():
                    # Auto-downgrade
                    db_user.tier = "free"
                    db_user.subscription_status = "expired"
                    await s.commit()
                    raise HTTPException(
                        403,
                        "Your subscription has expired. Please renew to continue using paid features."
                    )
                # Refresh JWT tier from DB in case webhook updated it
                if db_user.tier != user_tier:
                    user["tier"] = db_user.tier

        return user
    return checker


# -- Combined JWT or API-key auth (for B2B consumers) -------------

from fastapi.security.api_key import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _user_from_api_key(api_key: str) -> Optional[dict]:
    if not api_key:
        return None
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    async with SessionLocal() as s:
        row = (await s.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
        )).scalar_one_or_none()
        if not row:
            return None
        # Update last_used_at
        row.last_used_at = datetime.utcnow()
        await s.commit()
        user = (await s.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
        if not user:
            return None
        return {"sub": str(user.id), "email": user.email, "tier": user.tier,
                "via": "api_key", "key_id": row.id}


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(auth_scheme),
    api_key: Optional[str] = Depends(_api_key_header),
) -> dict:
    """Accept EITHER a Bearer JWT (browser sessions) OR an X-API-Key header
    (B2B consumers). Raises 401 if neither resolves to a real user."""
    if credentials:
        u = await get_current_user(credentials)
        if u:
            return u
    if api_key:
        u = await _user_from_api_key(api_key)
        if u:
            return u
    raise HTTPException(401, "Authentication required — provide a Bearer token or X-API-Key header")


# -- Routes -------------------------------------

@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest):
    async with SessionLocal() as s:
        existing = await s.execute(select(User).where(User.email == req.email))
        if existing.scalar_one_or_none():
            raise HTTPException(409, "Email already registered")

        user = User(
            email=req.email,
            password_hash=pwd_context.hash(req.password),
            display_name=req.display_name or req.email.split("@")[0],
            tier="free",
        )
        s.add(user)
        await s.flush()

        access = create_access_token(user)
        refresh = create_refresh_token(user)

        from app.store import store as st
        await st.r.set(f"refresh:{user.id}", refresh, ex=REFRESH_EXPIRE_DAYS * 86400)

        await s.commit()

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user={
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "tier": user.tier,
            "created_at": user.created_at.isoformat(),
        },
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    async with SessionLocal() as s:
        result = await s.execute(select(User).where(User.email == req.email, User.is_active == True))
        user = result.scalar_one_or_none()
        if not user or not pwd_context.verify(req.password, user.password_hash):
            raise HTTPException(401, "Invalid email or password")

        access = create_access_token(user)
        refresh = create_refresh_token(user)

        from app.store import store as st
        await st.r.set(f"refresh:{user.id}", refresh, ex=REFRESH_EXPIRE_DAYS * 86400)

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user={
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "tier": user.tier,
            "created_at": user.created_at.isoformat(),
        },
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: dict):
    """Exchange a valid refresh token for a new access + refresh pair."""
    refresh_token = req.get("refresh_token")
    if not refresh_token:
        raise HTTPException(400, "Missing refresh_token")

    payload = _decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid refresh token")

    user_id = payload["sub"]
    async with SessionLocal() as s:
        result = await s.execute(select(User).where(User.id == user_id, User.is_active == True))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(401, "User not found")

        access = create_access_token(user)
        refresh = create_refresh_token(user)

        from app.store import store as st
        await st.r.set(f"refresh:{user.id}", refresh, ex=REFRESH_EXPIRE_DAYS * 86400)

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user={
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "tier": user.tier,
            "created_at": user.created_at.isoformat(),
        },
    )


@router.get("/me", response_model=UserProfile)
async def me(user: dict = Depends(require_user)):
    """Return fresh user profile from DB (includes current tier)."""
    async with SessionLocal() as s:
        result = await s.execute(select(User).where(User.id == user["sub"]))
        db_user = result.scalar_one_or_none()
        if not db_user:
            raise HTTPException(404, "User not found")
    return UserProfile(
        id=db_user.id,
        email=db_user.email,
        display_name=db_user.display_name or "",
        tier=db_user.tier,
        created_at=db_user.created_at.isoformat(),
    )


@router.post("/logout")
async def logout(user: dict = Depends(require_user)):
    """Invalidate the user's refresh token in Redis."""
    from app.store import store as st
    await st.r.delete(f"refresh:{user['sub']}")
    return {"ok": True}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
async def change_password(req: ChangePasswordRequest, user_data: dict = Depends(require_user)):
    """Change authenticated user's password. Requires current password for verification."""
    if len(req.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    async with SessionLocal() as s:
        result = await s.execute(select(User).where(User.id == user_data["sub"]))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(404, "User not found")
        if not pwd_context.verify(req.current_password, user.password_hash):
            raise HTTPException(400, "Current password is incorrect")
        user.password_hash = pwd_context.hash(req.new_password)
        await s.commit()
    # Invalidate all existing sessions so other devices must re-login
    from app.store import store as st
    await st.r.delete(f"refresh:{user_data['sub']}")
    return {"ok": True}


@router.post("/tier")
async def update_tier(req: TierUpdateRequest, user: dict = Depends(require_user)):
    """Update the user's subscription tier. In production this would integrate
    with Razorpay; for now it's a direct DB update."""
    valid_tiers = {"free", "pro", "algo"}
    if req.tier not in valid_tiers:
        raise HTTPException(400, f"Invalid tier. Must be one of: {', '.join(valid_tiers)}")

    async with SessionLocal() as s:
        result = await s.execute(select(User).where(User.id == user["sub"]))
        db_user = result.scalar_one_or_none()
        if not db_user:
            raise HTTPException(404, "User not found")
        db_user.tier = req.tier
        await s.commit()

    return {"ok": True, "tier": req.tier}


# -- API key management -------------------------

class CreateApiKeyRequest(BaseModel):
    name: str = "default"


@router.get("/api-keys")
async def list_api_keys(user: dict = Depends(require_user)):
    async with SessionLocal() as s:
        rows = await s.execute(
            select(ApiKey).where(ApiKey.user_id == user["sub"], ApiKey.is_active == True)
        )
        keys = rows.scalars().all()
    return {"keys": [
        {
            "id": k.id,
            "label": k.name,
            "key_preview": "reyu_••••••••",
            "created_at": k.created_at.isoformat(),
            "last_used": k.last_used_at.isoformat() if k.last_used_at else None,
        }
        for k in keys
    ]}


@router.post("/api-keys")
async def create_api_key(req: CreateApiKeyRequest, user: dict = Depends(require_user)):
    raw_key = "reyu_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    async with SessionLocal() as s:
        ak = ApiKey(user_id=user["sub"], key_hash=key_hash, name=req.name)
        s.add(ak)
        await s.commit()
    return {"key": raw_key, "name": req.name, "id": ak.id}


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str, user: dict = Depends(require_user)):
    async with SessionLocal() as s:
        row = await s.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user["sub"]))
        ak = row.scalar_one_or_none()
        if not ak:
            raise HTTPException(404, "API key not found")
        ak.is_active = False
        await s.commit()
    return {"ok": True}
