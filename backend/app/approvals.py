"""Approve-from-phone — pending actions resolved via Telegram (task #75).

Flow:
  1. A producer (today: the equity paper-live morning cycle, for
     strategies with entry_rules.require_approval) calls
     create_approval(): the action is parked in Redis (6h TTL) and the
     owner gets a Telegram DM with inline Approve / Skip buttons.
  2. The user taps a button → Telegram calls our webhook with a
     callback_query → resolve_approval() validates the chat belongs to
     the approval's owner, executes (or skips) the action, and answers.
  3. No tap before expiry → the approval lapses; buttons answer
     "expired" after the fact. Expiry = the action does NOT happen —
     fail-closed, consistent with the platform's approval-first stance.

Approvals are PAPER-scope today (paper entries). The same rails are the
compliance story for LIVE approvals later (F-B3+): every real-money
action gets an explicit, audited human yes.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from app.store import store

log = logging.getLogger("reyu.approvals")

TTL_SEC = 6 * 3600
_KEY = "approval:{}"


async def _send_with_buttons(chat_id: str, text: str, approval_id: str) -> bool:
    """Telegram DM with inline Approve/Skip keyboard. Never raises."""
    try:
        import httpx
        from app.routers.telegram import TG_API
        if not TG_API:
            log.warning("telegram not configured; approval %s has no channel", approval_id)
            return False
        async with httpx.AsyncClient(timeout=8) as c:
            await c.post(f"{TG_API}/sendMessage", json={
                "chat_id": chat_id, "text": text, "parse_mode": "Markdown",
                "reply_markup": {"inline_keyboard": [[
                    {"text": "✅ Approve", "callback_data": f"apr:{approval_id}:y"},
                    {"text": "⏭ Skip", "callback_data": f"apr:{approval_id}:n"},
                ]]},
            })
        return True
    except Exception as e:
        log.warning("approval DM failed: %s", e)
        return False


async def create_approval(user_id: str, kind: str, payload: dict,
                          message: str) -> str | None:
    """Park an action pending the owner's phone approval. Returns the
    approval id, or None when the user has no Telegram linked (caller
    decides the fallback)."""
    from sqlalchemy import select
    from app.db import SessionLocal, User
    async with SessionLocal() as s:
        u = (await s.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not u or not u.telegram_chat_id:
        return None

    aid = str(uuid.uuid4())[:8]
    await store.r.set(_KEY.format(aid), json.dumps({
        "user_id": user_id, "kind": kind, "payload": payload,
        "status": "PENDING", "created": datetime.utcnow().isoformat(),
    }), ex=TTL_SEC)
    if not await _send_with_buttons(u.telegram_chat_id, message, aid):
        await store.r.delete(_KEY.format(aid))
        return None
    log.info("approval %s created kind=%s user=%s", aid, kind, user_id)
    return aid


async def resolve_approval(approval_id: str, approve: bool, chat_id: str) -> str:
    """Handle a button tap. Returns the text to show the user. Validates
    the tapping chat belongs to the approval's owner; idempotent on
    double-taps; executes the parked action on approve."""
    raw = await store.r.get(_KEY.format(approval_id))
    if not raw:
        return "⌛ This request expired — no action was taken."
    rec = json.loads(raw)

    from sqlalchemy import select
    from app.db import SessionLocal, User
    async with SessionLocal() as s:
        u = (await s.execute(
            select(User).where(User.id == rec["user_id"])
        )).scalar_one_or_none()
    if not u or str(u.telegram_chat_id) != str(chat_id):
        return "This request belongs to a different account."
    if rec["status"] != "PENDING":
        return f"Already {rec['status'].lower()} — nothing more to do."

    rec["status"] = "APPROVED" if approve else "SKIPPED"
    rec["resolved"] = datetime.utcnow().isoformat()
    await store.r.set(_KEY.format(approval_id), json.dumps(rec), ex=86400)

    from app.audit import record as _audit
    await _audit(event_type="APPROVAL_" + rec["status"],
                 actor_id=rec["user_id"], actor_email=u.email,
                 resource_type="approval", resource_id=approval_id,
                 action=f"{rec['kind']} via Telegram",
                 meta=rec["payload"])

    if not approve:
        return "⏭ Skipped — no entry today."

    # ── Execute the parked action ────────────────────────────────
    if rec["kind"] == "EQUITY_PAPER_ENTRY":
        from app.strategy.equity_paper_live import execute_approved_entry
        result = await execute_approved_entry(rec["payload"]["strategy_id"])
        if result.get("entered"):
            return (f"✅ Entered (paper): {result['qty']} × "
                    f"{rec['payload'].get('symbol', '')} @ ₹{result['price']:,.2f}")
        return f"Couldn't enter: {result.get('reason', 'unknown')} — no position opened."

    return "Approved — but I don't know how to execute this action kind."
