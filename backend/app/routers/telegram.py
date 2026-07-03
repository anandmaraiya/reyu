"""Telegram bot bridge.

Two ends of the integration:

  1. /api/telegram/webhook       — Telegram POSTs every incoming message
                                    here. We look up the chat_id, route to
                                    the existing chat agent, and reply.
  2. /api/telegram/link/start    — user-facing endpoint that mints a 6-digit
                                    code and stores `tg:link:<code> = user_id`
                                    in Redis (10-min TTL). User DMs the bot
                                    `/link <code>` and the bot binds their
                                    chat_id to that user_id.

Configuration: set BOT_TOKEN in .env. Configure the webhook once via:
   curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<your-public-url>/api/telegram/webhook"
"""
from __future__ import annotations

import os
import secrets
import logging
from io import BytesIO

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update

from app.agent import router as intent_router
from app.agent.tools import call_tool
from app.db import SessionLocal, User
from app.routers.user_auth import require_user
from app.store import store
from app.config import settings

log = logging.getLogger("reyu.telegram")
router = APIRouter()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None
LINK_TTL_SEC = 10 * 60


# ── helpers ──────────────────────────────────────────────────
async def _send_message(chat_id: str | int, text: str) -> None:
    if not TG_API:
        log.warning("TELEGRAM_BOT_TOKEN not configured; would send: %s", text)
        return
    async with httpx.AsyncClient(timeout=8) as c:
        await c.post(f"{TG_API}/sendMessage", json={
            "chat_id": chat_id, "text": text, "parse_mode": "Markdown",
        })


async def _send_photo(chat_id: str | int, image_bytes: bytes, caption: str = "") -> None:
    if not TG_API:
        return
    async with httpx.AsyncClient(timeout=15) as c:
        files = {"photo": ("chart.png", image_bytes, "image/png")}
        await c.post(f"{TG_API}/sendPhoto",
                     data={"chat_id": str(chat_id), "caption": caption[:1024], "parse_mode": "Markdown"},
                     files=files)


async def _fetch_chart(chart_path: str | None, chart_post: dict | None) -> bytes | None:
    """The tool may return either:
        chart: '/api/chart/oi?symbol=...'   (GET)
        chart_post: {url: '/api/chart/payoff', body: {...}}  (POST)
    Hit either by calling the FastAPI app internally over localhost.
    """
    base = f"http://localhost:{os.environ.get('PORT', '8000')}"
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            if chart_path:
                r = await c.get(base + chart_path)
                return r.content if r.status_code == 200 else None
            if chart_post:
                r = await c.post(base + chart_post["url"], json=chart_post["body"])
                return r.content if r.status_code == 200 else None
        except Exception as e:
            log.warning("chart fetch failed: %s", e)
    return None


async def _user_by_chat_id(chat_id: str) -> dict | None:
    async with SessionLocal() as s:
        row = (await s.execute(select(User).where(User.telegram_chat_id == chat_id))).scalar_one_or_none()
        if not row:
            return None
        return {"sub": row.id, "email": row.email, "tier": row.tier, "via": "telegram"}


# ── link flow ────────────────────────────────────────────────
class LinkStartResponse(BaseModel):
    code: str
    bot_username: str
    expires_in: int


@router.post("/link/start", response_model=LinkStartResponse)
async def link_start(user: dict = Depends(require_user)):
    """Issue a 6-digit code. User DMs `/link <code>` to the bot."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    await store.r.set(f"tg:link:{code}", user["sub"], ex=LINK_TTL_SEC)
    return LinkStartResponse(
        code=code,
        bot_username=os.environ.get("TELEGRAM_BOT_USERNAME", "reyu_ai_bot"),
        expires_in=LINK_TTL_SEC,
    )


@router.post("/link/unlink")
async def link_unlink(user: dict = Depends(require_user)):
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == user["sub"]).values(telegram_chat_id=None))
        await s.commit()
    return {"ok": True}


# ── webhook from Telegram ────────────────────────────────────
@router.post("/webhook")
async def webhook(request: Request):
    """Telegram delivers every message here. No auth — we identify the user
    by matching `message.chat.id` to `users.telegram_chat_id`."""
    if not BOT_TOKEN:
        raise HTTPException(503, "Telegram bot not configured (TELEGRAM_BOT_TOKEN missing)")
    body = await request.json()

    # ── Inline-button taps (approve-from-phone, task #75) ─────────
    cq = body.get("callback_query")
    if cq:
        data = cq.get("data") or ""
        cq_chat = str(((cq.get("message") or {}).get("chat") or {}).get("id") or "")
        # Acknowledge the tap so the client stops its spinner.
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                await c.post(f"{TG_API}/answerCallbackQuery",
                             json={"callback_query_id": cq.get("id")})
        except Exception:
            pass
        if data.startswith("apr:") and cq_chat:
            _, aid, decision = (data.split(":") + ["", ""])[:3]
            from app.approvals import resolve_approval
            try:
                outcome = await resolve_approval(aid, decision == "y", cq_chat)
            except Exception as e:
                log.exception("approval resolve failed: %s", e)
                outcome = "Something went wrong resolving this — nothing was executed."
            await _send_message(cq_chat, outcome)
        return {"ok": True}

    msg = body.get("message") or body.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    text = (msg.get("text") or "").strip()
    if not chat_id or not text:
        return {"ok": True}

    # /start or /link <code>
    if text.startswith("/start"):
        await _send_message(chat_id,
            "👋 Welcome to *Reyu.ai* — your options co-pilot.\n"
            "Send `/link <code>` (get the code from Settings → Notifications → Link Telegram) "
            "to connect this chat to your account.\n\n"
            "Once linked, just ask questions like:\n"
            "• What's the NIFTY bias?\n"
            "• Suggest a hedge for selling NIFTY ATM CE\n"
            "• Any scalping setups in F&O Liquid?")
        return {"ok": True}

    if text.startswith("/link"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await _send_message(chat_id, "Send `/link <code>` — find the code in Settings → Notifications → Link Telegram.")
            return {"ok": True}
        code = parts[1].strip()
        uid = await store.r.get(f"tg:link:{code}")
        if not uid:
            await _send_message(chat_id, "❌ That code is invalid or expired. Generate a fresh one in the web app and try again.")
            return {"ok": True}
        async with SessionLocal() as s:
            await s.execute(update(User).where(User.id == uid).values(telegram_chat_id=chat_id))
            await s.commit()
        await store.r.delete(f"tg:link:{code}")
        await _send_message(chat_id, "✅ Linked. You can now ask me anything about options — try \"NIFTY bias today\".")
        return {"ok": True}

    # Identify the user
    user = await _user_by_chat_id(chat_id)
    if not user:
        await _send_message(chat_id,
            "🔒 This chat isn't linked yet. In the web app go to **Settings → Notifications → Link Telegram**, "
            "copy the 6-digit code, then send `/link <code>` here.")
        return {"ok": True}

    # Route the message through the same agent the web chat uses
    decision = intent_router.route(text)
    if "error" in decision:
        await _send_message(chat_id, decision["error"])
        return {"ok": True}
    result = await call_tool(decision["tool"], decision["args"], user)

    # Send text first, then chart if available
    chart_bytes = None
    if result.get("chart") or result.get("chart_post"):
        chart_bytes = await _fetch_chart(result.get("chart"), result.get("chart_post"))

    if chart_bytes:
        await _send_photo(chat_id, chart_bytes, caption=result.get("text", "")[:1024])
    else:
        await _send_message(chat_id, result.get("text", "Sorry — nothing to show."))

    return {"ok": True}
