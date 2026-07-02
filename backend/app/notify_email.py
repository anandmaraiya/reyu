"""Resend transactional email — thin HTTP wrapper.

Why direct HTTP over the SDK: one fewer dependency, and the SDK doesn't
buy us anything on top of a single POST call. Same pattern already used
for Fyers.

Usage:
    from app.notify_email import send_email
    await send_email(
        to="user@example.com",
        subject="Reset your Reyu password",
        html="<p>Click ...</p>",
    )

Falls back to log-only when `RESEND_API_KEY` is unset — safe for
local dev where you don't want to burn API quota or send real mail.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.config import settings

log = logging.getLogger("reyu.notify_email")


async def send_email(
    to: str,
    subject: str,
    html: str,
    *,
    from_email: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> dict:
    """Send a transactional email via Resend. Returns {ok, id | error}."""
    if not settings.resend_api_key:
        log.warning("[email-stub] to=%s subject=%r (RESEND_API_KEY unset)",
                    to, subject)
        return {"ok": False, "stub": True, "reason": "no_api_key"}

    payload: dict = {
        "from": from_email or settings.resend_from_email,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if reply_to:
        payload["reply_to"] = reply_to

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.RequestError as e:
            log.exception("resend request failed to=%s: %s", to, e)
            return {"ok": False, "error": str(e)}

    if r.status_code >= 400:
        log.warning("resend rejected to=%s status=%s body=%s",
                    to, r.status_code, r.text[:200])
        return {"ok": False, "status": r.status_code, "error": r.text[:500]}

    body = r.json()
    log.info("email sent to=%s id=%s", to, body.get("id"))
    return {"ok": True, "id": body.get("id")}


# ── Templates ─────────────────────────────────────────────────────────
def password_reset_html(reset_url: str, valid_minutes: int = 30) -> str:
    return f"""
    <div style="font-family:-apple-system,sans-serif;max-width:520px;margin:0 auto;padding:32px 24px;color:#1a1a1a">
      <h1 style="font-size:20px;margin:0 0 12px 0">Reset your Reyu password</h1>
      <p style="line-height:1.5;color:#555">
        You (or someone using your email) asked to reset the password
        for your Reyu account. Click the button below to choose a new
        password. This link is valid for {valid_minutes} minutes.
      </p>
      <p style="margin:24px 0">
        <a href="{reset_url}" style="background:#059669;color:#fff;text-decoration:none;padding:12px 20px;border-radius:6px;font-weight:600;display:inline-block">
          Reset password
        </a>
      </p>
      <p style="font-size:13px;color:#888;line-height:1.5">
        If you didn't request this, safe to ignore — your password won't change.
      </p>
      <p style="font-size:12px;color:#aaa;margin-top:32px">
        Reyu — AI Options Copilot · <a href="https://reyu.ai" style="color:#888">reyu.ai</a>
      </p>
    </div>
    """


def _wrap(inner_html: str) -> str:
    """Shared shell — header, brand color, footer. All drip templates use this."""
    return f"""
    <div style="font-family:-apple-system,sans-serif;max-width:520px;margin:0 auto;padding:32px 24px;color:#1a1a1a">
      {inner_html}
      <p style="font-size:12px;color:#aaa;margin-top:32px;border-top:1px solid #eee;padding-top:12px">
        Reyu — AI Options Copilot · <a href="https://reyu.ai" style="color:#888">reyu.ai</a><br/>
        You're getting this because you signed up. Reply to unsubscribe.
      </p>
    </div>
    """


def drip_day1_html(display_name: str, dashboard_url: str) -> str:
    """24h post-signup — nudge on connecting a broker."""
    return _wrap(f"""
      <h1 style="font-size:20px;margin:0 0 12px 0">Ready to see live signals, {display_name}?</h1>
      <p style="line-height:1.5;color:#555">
        Yesterday you signed up for Reyu. To unlock live option chains,
        regime-router paper trades, and personalised AI answers,
        connect your Fyers account. It takes about 45 seconds.
      </p>
      <p style="margin:24px 0">
        <a href="{dashboard_url}/brokers" style="background:#059669;color:#fff;text-decoration:none;padding:12px 20px;border-radius:6px;font-weight:600;display:inline-block">
          Connect Fyers
        </a>
      </p>
      <p style="font-size:13px;color:#888;line-height:1.5">
        Don't have a Fyers account? Zerodha + Upstox support ships next month.
      </p>
    """)


def drip_day3_html(display_name: str, dashboard_url: str) -> str:
    """3-day nudge — try a backtest."""
    return _wrap(f"""
      <h1 style="font-size:20px;margin:0 0 12px 0">Test a strategy in 30 seconds</h1>
      <p style="line-height:1.5;color:#555">
        {display_name}, most Reyu users find their edge in the backtest.
        The regime router hit <strong>+975% ROI with 9.5% drawdown</strong>
        on 2019-2024 NIFTY. See the exact trades:
      </p>
      <p style="margin:24px 0">
        <a href="{dashboard_url}/backtest" style="background:#059669;color:#fff;text-decoration:none;padding:12px 20px;border-radius:6px;font-weight:600;display:inline-block">
          Run a backtest
        </a>
      </p>
      <p style="font-size:12px;color:#888;line-height:1.5">
        Pro tip: run 2019, 2020, 2022 windows separately to see how the
        strategy handles very different regimes.
      </p>
    """)


def drip_day7_html(display_name: str, dashboard_url: str) -> str:
    """1-week retention — highlight the paper-live platform strategy."""
    return _wrap(f"""
      <h1 style="font-size:20px;margin:0 0 12px 0">A week in — here's what's running for you</h1>
      <p style="line-height:1.5;color:#555">
        The Reyu regime router opened its next paper trade at 9:25 IST today.
        It picks between long CE, long PE, and iron condor based on
        yesterday's PCR + 3-day momentum, then hard-closes at 15:20 IST.
        No overnight risk.
      </p>
      <p style="line-height:1.5;color:#555">
        Watch it on the Journal page. When you're ready, promote it to
        live with the Algo plan.
      </p>
      <p style="margin:24px 0">
        <a href="{dashboard_url}/journal" style="background:#059669;color:#fff;text-decoration:none;padding:12px 20px;border-radius:6px;font-weight:600;display:inline-block">
          Open my journal
        </a>
      </p>
    """)


def welcome_html(display_name: str, dashboard_url: str) -> str:
    return f"""
    <div style="font-family:-apple-system,sans-serif;max-width:520px;margin:0 auto;padding:32px 24px;color:#1a1a1a">
      <h1 style="font-size:20px;margin:0 0 12px 0">Welcome to Reyu, {display_name}!</h1>
      <p style="line-height:1.5;color:#555">
        Your AI options copilot is ready. Next steps:
      </p>
      <ol style="line-height:1.6;color:#555">
        <li>Connect your Fyers broker so we can access live chain data</li>
        <li>Run a backtest on any NIFTY strategy in one click</li>
        <li>Watch the regime-router paper-live in action tomorrow at 09:25 IST</li>
      </ol>
      <p style="margin:24px 0">
        <a href="{dashboard_url}" style="background:#059669;color:#fff;text-decoration:none;padding:12px 20px;border-radius:6px;font-weight:600;display:inline-block">
          Open dashboard
        </a>
      </p>
      <p style="font-size:12px;color:#aaa;margin-top:32px">
        Reyu — AI Options Copilot · <a href="https://reyu.ai" style="color:#888">reyu.ai</a>
      </p>
    </div>
    """
