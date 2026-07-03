"""Per-user notifications — trade alerts + morning digest (P2b).

The existing app.notify fans out to GLOBAL admin webhooks; this module
notifies the OWNING USER of a strategy through channels they control:

  * Telegram DM   — if users.telegram_chat_id is linked (instant, cheap)
  * Email         — morning digest only (per-trade email would be spam)

Everything here is fire-and-forget: a notification failure must never
break the trading path. All senders swallow + log.

Used by:
  * app.strategy.paper_live  — trade opened / closed alerts
  * app.scheduler            — morning_digest_job (08:30 IST weekdays)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, text

from app.db import SessionLocal, User

log = logging.getLogger("reyu.digest")


async def _telegram_dm(user_id: str, message: str) -> bool:
    """Send a Telegram DM to a user if they've linked a chat. Never raises."""
    try:
        async with SessionLocal() as s:
            u = (await s.execute(
                select(User).where(User.id == user_id)
            )).scalar_one_or_none()
        if not u or not u.telegram_chat_id:
            return False
        from app.routers.telegram import _send_message
        await _send_message(u.telegram_chat_id, message)
        return True
    except Exception as e:
        log.warning("telegram dm to %s failed: %s", user_id, e)
        return False


# ── Trade alerts (paper/live) ───────────────────────────────────────
async def alert_trade_opened(owner_id: str, strategy_name: str, mode: str,
                             symbol: str, qty: int, price: float) -> None:
    await _telegram_dm(owner_id,
        f"🟢 *{strategy_name}* ({mode}) entered\n"
        f"{symbol} · {qty} @ ₹{price:,.2f}")


async def alert_trade_closed(owner_id: str, strategy_name: str, mode: str,
                             symbol: str, reason: str, pnl_inr: float) -> None:
    emoji = "✅" if pnl_inr >= 0 else "🔻"
    await _telegram_dm(owner_id,
        f"{emoji} *{strategy_name}* ({mode}) closed — {reason}\n"
        f"{symbol} · P&L ₹{pnl_inr:+,.2f}")


# ── Morning digest ──────────────────────────────────────────────────
async def send_morning_digest() -> dict:
    """One digest per user with RUNNING paper/live runs: what's active,
    yesterday's realised P&L, open position count. Telegram + email.
    Called by the scheduler weekdays ~08:30 IST (03:00 UTC)."""
    y_start = (datetime.utcnow() - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    y_end = y_start + timedelta(days=1)

    async with SessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT r.owner_id,
                   COUNT(DISTINCT r.strategy_id)                        AS strategies,
                   ARRAY_AGG(DISTINCT st.name)                          AS names,
                   ARRAY_AGG(DISTINCT r.mode)                           AS modes,
                   COALESCE(SUM(CASE WHEN t.exit_ts >= :ys AND t.exit_ts < :ye
                       THEN COALESCE(t.net_pnl_inr, t.gross_pnl_inr, 0) END), 0) AS pnl_yday,
                   COUNT(CASE WHEN t.exit_ts IS NULL THEN 1 END)        AS open_pos
            FROM strategy_runs r
            JOIN strategies st ON st.id = r.strategy_id AND st.version = r.strategy_version
            LEFT JOIN strategy_trades t ON t.run_id = r.id
            WHERE r.status = 'RUNNING' AND r.mode IN ('PAPER','LIVE')
            GROUP BY r.owner_id
        """), {"ys": y_start, "ye": y_end})).fetchall()

        sent_tg = sent_email = 0
        for r in rows:
            u = (await s.execute(
                select(User).where(User.id == r.owner_id)
            )).scalar_one_or_none()
            if not u:
                continue
            names = ", ".join((r.names or [])[:5])
            modes = "+".join(sorted(r.modes or []))
            pnl = float(r.pnl_yday or 0)

            tg_msg = (
                f"☀️ *Reyu morning digest*\n"
                f"{r.strategies} strategies running ({modes}): {names}\n"
                f"Yesterday realised: ₹{pnl:+,.2f}\n"
                f"Open positions: {r.open_pos}"
            )
            if await _telegram_dm(u.id, tg_msg):
                sent_tg += 1

            try:
                from app.notify_email import send_email
                display = u.display_name or u.email.split("@")[0]
                html = (
                    f"<p>Good morning {display},</p>"
                    f"<p><b>{r.strategies}</b> of your strategies are running "
                    f"({modes}): {names}.</p>"
                    f"<p>Yesterday's realised P&amp;L: <b>₹{pnl:+,.2f}</b> · "
                    f"Open positions: <b>{r.open_pos}</b></p>"
                    f"<p>Review or halt anytime from your "
                    f"<a href='https://reyu.ai/portfolio'>Portfolio</a>.</p>"
                    f"<p style='color:#888;font-size:12px'>Reyu automates your own "
                    f"strategies — it doesn't give investment advice. "
                    f"Derivatives trading is high-risk.</p>"
                )
                await send_email(u.email, "Your Reyu morning digest", html)
                sent_email += 1
            except Exception as e:
                log.warning("digest email to %s failed: %s", u.email, e)

    log.info("morning digest: %d telegram, %d email", sent_tg, sent_email)
    return {"users": len(rows), "telegram": sent_tg, "email": sent_email}
