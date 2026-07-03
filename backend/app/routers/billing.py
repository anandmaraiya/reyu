"""Razorpay billing: subscription creation, webhook handling, plan management.

Endpoints:
  POST /api/billing/create-subscription  — start a new Razorpay subscription
  POST /api/billing/webhook              — Razorpay webhook callbacks
  GET  /api/billing/status               — current user's subscription status
  POST /api/billing/cancel               — cancel at period end
  POST /api/billing/change-plan          — schedule plan change at period end
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, User
from app.routers.user_auth import require_user

router = APIRouter()

# -- Tier → Razorpay plan mapping ----------------

TIER_PLANS = {
    ("pro", "month"): settings.razorpay_plan_pro_monthly,
    ("pro", "year"): settings.razorpay_plan_pro_yearly,
    ("algo", "month"): settings.razorpay_plan_algo_monthly,
    ("algo", "year"): settings.razorpay_plan_algo_yearly,
}

# Prices in paise (1 INR = 100 paise). Must match the amounts configured
# on the Razorpay plan IDs above (Razorpay dashboard) AND the display
# prices in frontend/src/pages/Subscription.tsx.
TIER_PRICES = {
    ("pro", "month"): 200000,     # ₹2,000
    ("pro", "year"): 1920000,     # ₹19,200 (₹1,600/mo)
    ("algo", "month"): 990000,    # ₹9,900
    ("algo", "year"): 9480000,    # ₹94,800 (₹7,900/mo)
}


def _razorpay_auth() -> tuple:
    return (settings.razorpay_key_id, settings.razorpay_key_secret)


# -- Pydantic models ----------------------------

class CreateSubscriptionRequest(BaseModel):
    tier: str   # pro | algo
    cycle: str  # month | year


class ChangePlanRequest(BaseModel):
    tier: str   # pro | algo
    cycle: str  # month | year


class SubscriptionStatusResponse(BaseModel):
    tier: str
    subscription_id: Optional[str]
    subscription_status: Optional[str]
    subscription_ends_at: Optional[str]
    pending_plan: Optional[str]


# -- Routes -------------------------------------

@router.post("/create-subscription")
async def create_subscription(
    req: CreateSubscriptionRequest,
    user: dict = Depends(require_user),
):
    """Create a Razorpay subscription for the authenticated user.

    Flow:
    1. Look up or create a Razorpay customer for this user
    2. Create a subscription on the pre-configured Razorpay plan
    3. Return the Razorpay subscription_id + short-lived auth token
       so the frontend can open the Razorpay checkout modal.
    """
    if req.tier not in ("pro", "algo"):
        raise HTTPException(400, "Tier must be 'pro' or 'algo'")
    if req.cycle not in ("month", "year"):
        raise HTTPException(400, "Cycle must be 'month' or 'year'")

    plan_id = TIER_PLANS.get((req.tier, req.cycle))
    if not plan_id:
        raise HTTPException(500, f"Razorpay plan not configured for {req.tier}/{req.cycle}")

    async with SessionLocal() as s:
        result = await s.execute(select(User).where(User.id == user["sub"]))
        db_user = result.scalar_one_or_none()
        if not db_user:
            raise HTTPException(404, "User not found")

        # Get or create Razorpay customer
        customer_id = db_user.razorpay_customer_id
        if not customer_id:
            customer_id = await _create_razorpay_customer(db_user)
            db_user.razorpay_customer_id = customer_id
            await s.flush()

        # Create Razorpay subscription
        sub_data = await _create_razpay_subscription(customer_id, plan_id, req.tier, req.cycle)

        # Store subscription info
        db_user.subscription_id = sub_data["id"]
        db_user.subscription_status = sub_data.get("status", "created")
        await s.commit()

    return {
        "subscription_id": sub_data["id"],
        "razorpay_key": settings.razorpay_key_id,
        "razorpay_short_url": sub_data.get("short_url", ""),
        "tier": req.tier,
        "cycle": req.cycle,
        "amount": TIER_PRICES[(req.tier, req.cycle)],
        "currency": "INR",
        "callback_url": settings.razorpay_callback_url,
        "customer": {
            "name": db_user.display_name or db_user.email,
            "email": db_user.email,
        },
    }


@router.get("/status", response_model=SubscriptionStatusResponse)
async def subscription_status(user: dict = Depends(require_user)):
    """Return the current user's subscription status from our DB."""
    async with SessionLocal() as s:
        result = await s.execute(select(User).where(User.id == user["sub"]))
        db_user = result.scalar_one_or_none()
        if not db_user:
            raise HTTPException(404, "User not found")

    return SubscriptionStatusResponse(
        tier=db_user.tier,
        subscription_id=db_user.subscription_id,
        subscription_status=db_user.subscription_status,
        subscription_ends_at=db_user.subscription_ends_at.isoformat() if db_user.subscription_ends_at else None,
        pending_plan=db_user.pending_plan,
    )


@router.post("/cancel")
async def cancel_subscription(user: dict = Depends(require_user)):
    """Cancel the user's active Razorpay subscription at period end."""
    async with SessionLocal() as s:
        result = await s.execute(select(User).where(User.id == user["sub"]))
        db_user = result.scalar_one_or_none()
        if not db_user:
            raise HTTPException(404, "User not found")

        if not db_user.subscription_id:
            raise HTTPException(400, "No active subscription")

        # Cancel on Razorpay (at period end)
        await _cancel_razorpay_subscription(db_user.subscription_id)

        db_user.subscription_status = "cancelled"
        await s.commit()

    return {"ok": True, "message": "Subscription will cancel at period end"}


@router.post("/change-plan")
async def change_plan(
    req: ChangePlanRequest,
    user: dict = Depends(require_user),
):
    """Schedule a plan change at the end of the current billing period."""
    if req.tier not in ("pro", "algo"):
        raise HTTPException(400, "Tier must be 'pro' or 'algo'")
    if req.cycle not in ("month", "year"):
        raise HTTPException(400, "Cycle must be 'month' or 'year'")

    new_plan = TIER_PLANS.get((req.tier, req.cycle))
    if not new_plan:
        raise HTTPException(500, f"Razorpay plan not configured for {req.tier}/{req.cycle}")

    async with SessionLocal() as s:
        result = await s.execute(select(User).where(User.id == user["sub"]))
        db_user = result.scalar_one_or_none()
        if not db_user:
            raise HTTPException(404, "User not found")

        if not db_user.subscription_id:
            raise HTTPException(400, "No active subscription — create one first")

        # Update on Razorpay (schedule plan change)
        await _update_razorpay_plan(db_user.subscription_id, new_plan)

        db_user.pending_plan = f"{req.tier}:{req.cycle}"
        await s.commit()

    return {"ok": True, "pending_plan": f"{req.tier}:{req.cycle}"}


# -- Webhook (public, no auth) ------------------

@router.post("/webhook")
async def razorpay_webhook(request: Request):
    """Handle Razorpay webhook events.

    Verifies the webhook signature, then processes:
    - subscription.activated  → set tier, status=active
    - subscription.charged    → extend subscription_ends_at, refresh tier
    - subscription.cancelled  → revert tier to free
    - subscription.paused     → set status=paused
    - subscription.resumed    → set status=active
    """
    body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")

    # Verify signature
    if settings.razorpay_webhook_secret:
        expected = hmac.new(
            settings.razorpay_webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(400, "Invalid webhook signature")

    payload = json.loads(body)
    event = payload.get("event", "")
    sub_entity = (
        payload.get("payload", {})
        .get("subscription", {})
        .get("entity", {})
    )
    notes = sub_entity.get("notes", {})

    user_id = notes.get("user_id")
    tier = notes.get("tier", "free")

    if not user_id:
        # Some events (e.g. payment failed) may structure differently
        # Try to find user by subscription_id
        sub_id = sub_entity.get("id", "")
        if sub_id:
            async with SessionLocal() as s:
                result = await s.execute(
                    select(User).where(User.subscription_id == sub_id)
                )
                db_user = result.scalar_one_or_none()
                if db_user:
                    user_id = db_user.id
                    tier = db_user.tier

    if not user_id:
        return {"ok": True, "detail": "No user associated — skipped"}

    async with SessionLocal() as s:
        result = await s.execute(select(User).where(User.id == user_id))
        db_user = result.scalar_one_or_none()
        if not db_user:
            return {"ok": True, "detail": "User not found — skipped"}

        if event == "subscription.activated":
            db_user.tier = tier
            db_user.subscription_id = sub_entity.get("id", db_user.subscription_id)
            db_user.subscription_status = "active"
            ends_at = sub_entity.get("current_end")
            if ends_at:
                db_user.subscription_ends_at = datetime.utcfromtimestamp(ends_at)
            db_user.pending_plan = None

        elif event == "subscription.charged":
            db_user.subscription_status = "active"
            ends_at = sub_entity.get("current_end")
            if ends_at:
                db_user.subscription_ends_at = datetime.utcfromtimestamp(ends_at)
            # Ensure tier stays in sync
            if db_user.pending_plan:
                new_tier = db_user.pending_plan.split(":")[0]
                db_user.tier = new_tier
                db_user.pending_plan = None

        elif event == "subscription.cancelled":
            db_user.subscription_status = "cancelled"
            # Don't downgrade immediately — let them use until period end
            # A background job could check subscription_ends_at and downgrade

        elif event == "subscription.paused":
            db_user.subscription_status = "paused"

        elif event == "subscription.resumed":
            db_user.subscription_status = "active"

        elif event == "subscription.pending":
            db_user.subscription_status = "pending"

        elif event == "payment.failed":
            # Log but don't change tier — Razorpay will retry
            pass

        await s.commit()

    return {"ok": True, "event": event}


# -- Razorpay API helpers -----------------------

async def _create_razorpay_customer(user: User) -> str:
    """Create a Razorpay customer and return the customer ID."""
    if not settings.razorpay_key_id:
        # Dev mode — return a fake ID
        return f"cust_dev_{user.id[:8]}"

    async with httpx.AsyncClient(auth=_razorpay_auth()) as client:
        resp = await client.post(
            "https://api.razorpay.com/v1/customers",
            json={
                "name": user.display_name or user.email,
                "email": user.email,
                "fail_existing": 0,
            },
        )
        data = resp.json()
        if "id" in data:
            return data["id"]
        raise HTTPException(502, f"Razorpay customer creation failed: {data.get('error', data)}")


async def _create_razpay_subscription(
    customer_id: str, plan_id: str, tier: str, cycle: str
) -> dict:
    """Create a Razorpay subscription and return the subscription entity."""
    if not settings.razorpay_key_id:
        # Dev mode — return a fake subscription
        import uuid
        return {
            "id": f"sub_dev_{uuid.uuid4().hex[:12]}",
            "status": "created",
            "short_url": f"https://rzp.io/i/dev_{uuid.uuid4().hex[:8]}",
        }

    total_count = 120 if cycle == "year" else 12  # max billing cycles

    async with httpx.AsyncClient(auth=_razorpay_auth()) as client:
        resp = await client.post(
            "https://api.razorpay.com/v1/subscriptions",
            json={
                "plan_id": plan_id,
                "total_count": total_count,
                "quantity": 1,
                "customer_notify": 1,
                "notes": {"tier": tier, "cycle": cycle},
            },
        )
        data = resp.json()
        if "id" in data:
            return data
        raise HTTPException(502, f"Razorpay subscription creation failed: {data.get('error', data)}")


async def _cancel_razorpay_subscription(subscription_id: str) -> None:
    """Cancel a Razorpay subscription at period end."""
    if not settings.razorpay_key_id or subscription_id.startswith("sub_dev_"):
        return  # Dev mode — no-op

    async with httpx.AsyncClient(auth=_razorpay_auth()) as client:
        resp = await client.post(
            f"https://api.razorpay.com/v1/subscriptions/{subscription_id}/cancel",
            json={"cancel_at_cycle_end": True},
        )
        if resp.status_code not in (200, 201):
            data = resp.json()
            raise HTTPException(502, f"Razorpay cancel failed: {data.get('error', data)}")


async def _update_razorpay_plan(subscription_id: str, new_plan_id: str) -> None:
    """Schedule a plan change on an existing Razorpay subscription."""
    if not settings.razorpay_key_id or subscription_id.startswith("sub_dev_"):
        return  # Dev mode — no-op

    async with httpx.AsyncClient(auth=_razorpay_auth()) as client:
        resp = await client.post(
            f"https://api.razorpay.com/v1/subscriptions/{subscription_id}",
            json={
                "plan_id": new_plan_id,
                "schedule_change_at": "cycle_end",
            },
        )
        if resp.status_code not in (200, 201):
            data = resp.json()
            raise HTTPException(502, f"Razorpay plan change failed: {data.get('error', data)}")
