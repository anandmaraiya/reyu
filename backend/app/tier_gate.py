"""Tier gate — FastAPI dependencies for feature gating.

Usage:
    from app.tier_gate import require_login, require_paid, gate_strategy_save, gate_backtest_run

    @router.post("/strategies")
    async def save_strategy(request: Request, _=Depends(require_login)):
        ...

    @router.post("/strategies/{id}/runs")
    async def run_backtest(request: Request, _=Depends(gate_backtest_run)):
        ...

Error responses carry a `gate` field so the frontend knows which modal to show:
  - 401 + gate:"login"    → show login/signup modal
  - 402 + gate:"upgrade"  → show upgrade-to-paid modal
  - 402 + gate:"limit"    → show limit-reached modal (still on free tier)
  - 403 + gate:"trial"    → free trial expired

Tier limits:
    free  : 10 strategies, 50 backtest runs, no paper/live
    paid  : unlimited strategies + backtests, paper trading
    algo  : paid + live trading
"""
from __future__ import annotations

from datetime import datetime

from fastapi import Depends, HTTPException, Request

from app.db import SessionLocal, User
from sqlalchemy import select

# ── Limits ──────────────────────────────────────────────────────────────────
FREE_STRATEGY_LIMIT = 10
FREE_BACKTEST_LIMIT = 50
FREE_TRIAL_DAYS     = 15


def _gate(code: int, detail: str, gate: str):
    raise HTTPException(status_code=code, detail={"message": detail, "gate": gate})


# ── Low-level helpers ────────────────────────────────────────────────────────

def _user_from_request(request: Request) -> dict | None:
    return getattr(request.state, "user", None)


async def _db_user(user_dict: dict) -> User | None:
    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_dict["sub"]))
        return result.scalar_one_or_none()


# ── Public dependencies ──────────────────────────────────────────────────────

async def require_login(request: Request):
    """Endpoint requires any authenticated user (free or paid)."""
    user = _user_from_request(request)
    if not user:
        _gate(401, "Sign in to use this feature.", "login")
    return user


async def require_paid(request: Request):
    """Endpoint requires paid or algo tier."""
    user = _user_from_request(request)
    if not user:
        _gate(401, "Sign in to use this feature.", "login")
    tier = user.get("tier", "free")
    if tier not in ("paid", "algo"):
        _gate(402, "Upgrade to Pro ($20/mo) to unlock this feature.", "upgrade")
    return user


async def require_algo(request: Request):
    """Endpoint requires algo tier (live trading)."""
    user = _user_from_request(request)
    if not user:
        _gate(401, "Sign in to use this feature.", "login")
    if user.get("tier") != "algo":
        _gate(402, "Live trading requires the Algo tier.", "upgrade")
    return user


async def gate_strategy_save(request: Request):
    """Allow save if: paid tier OR (free + under 10 saves + trial active)."""
    user = _user_from_request(request)
    if not user:
        _gate(401, "Create a free account to save strategies.", "login")

    tier = user.get("tier", "free")
    if tier in ("paid", "algo"):
        return user

    # Free tier checks
    db_user = await _db_user(user)
    if not db_user:
        _gate(401, "User not found.", "login")

    if db_user.trial_expires_at and datetime.utcnow() > db_user.trial_expires_at:
        _gate(403, "Your 15-day free trial has expired. Upgrade to keep saving strategies.", "trial")

    if (db_user.strategy_count or 0) >= FREE_STRATEGY_LIMIT:
        _gate(402,
              f"Free tier allows {FREE_STRATEGY_LIMIT} saved strategies. "
              "Upgrade to Pro for unlimited saves.",
              "limit")
    return user


async def gate_backtest_run(request: Request):
    """Allow backtest if: paid tier OR (free + under 50 runs + trial active)."""
    user = _user_from_request(request)
    if not user:
        _gate(401, "Create a free account to run backtests.", "login")

    tier = user.get("tier", "free")
    if tier in ("paid", "algo"):
        return user

    db_user = await _db_user(user)
    if not db_user:
        _gate(401, "User not found.", "login")

    if db_user.trial_expires_at and datetime.utcnow() > db_user.trial_expires_at:
        _gate(403, "Your 15-day free trial has expired.", "trial")

    if (db_user.backtest_count or 0) >= FREE_BACKTEST_LIMIT:
        _gate(402,
              f"Free tier allows {FREE_BACKTEST_LIMIT} backtest runs. "
              "Upgrade to Pro for unlimited runs.",
              "limit")
    return user


async def gate_paper_trade(request: Request):
    """Paper trading requires paid tier."""
    user = _user_from_request(request)
    if not user:
        _gate(401, "Sign in to paper trade.", "login")
    if user.get("tier", "free") not in ("paid", "algo"):
        _gate(402, "Paper trading is available on the Pro plan ($20/mo).", "upgrade")
    return user


# ── Counter helpers (call after successful save/run) ─────────────────────────

async def increment_strategy_count(user_id: str):
    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        u = result.scalar_one_or_none()
        if u:
            u.strategy_count = (u.strategy_count or 0) + 1
            await db.commit()


async def decrement_strategy_count(user_id: str):
    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        u = result.scalar_one_or_none()
        if u:
            u.strategy_count = max(0, (u.strategy_count or 0) - 1)
            await db.commit()


async def increment_backtest_count(user_id: str):
    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        u = result.scalar_one_or_none()
        if u:
            u.backtest_count = (u.backtest_count or 0) + 1
            await db.commit()
