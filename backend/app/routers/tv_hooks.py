"""TradingView webhook-in — external signals drive paper trades (P3, #76).

    POST /api/hooks/tv/{strategy_id}/{token}   ← TradingView alert webhook
    GET  /api/strategies/{id}/tv-hook          ← owner fetches their URL

TradingView can't send auth headers, so auth is a per-strategy token in
the URL: HMAC-SHA256(jwt_secret, "tvhook:" + strategy_id) — deterministic,
nothing stored. (Rotating jwt_secret revokes all hooks; per-strategy
revocation is future work.)

Alert payload (JSON or plain text):
    {"action": "buy"}    open a paper position at the current quote
    {"action": "exit"}   close all open paper positions ("sell" = alias)
Plain-text bodies containing buy/sell/exit also work, so a bare
TradingView default message is enough.

Guardrails (deliberate MVP limits):
  * PAPER only — signals never place broker orders. The strategy must be
    in PAPER_LIVE status; entries land as paper trades in strategy_trades.
  * EQUITY_EOD strategies only — the universe symbol is directly
    tradable. Options strategies need strike/expiry resolution from a
    bare buy signal; that's future work.
  * Risk caps respected: max_concurrent positions, max_position_inr
    sizing. Every signal is audited (TV_SIGNAL) and the owner is
    alerted on Telegram.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, desc, func

from app.config import settings
from app.db import SessionLocal, Strategy, StrategyTrade
from app.strategy.spec import StrategySpec

log = logging.getLogger("reyu.tv_hooks")
router = APIRouter(prefix="/api/hooks/tv", tags=["tv-hooks"])
owner_router = APIRouter(prefix="/api/strategies", tags=["strategies"])


def hook_token(strategy_id: str) -> str:
    return hmac.new(settings.jwt_secret.encode(),
                    f"tvhook:{strategy_id}".encode(),
                    hashlib.sha256).hexdigest()[:32]


def _parse_action(body: bytes) -> str | None:
    """Extract buy/exit from a JSON or plain-text alert body."""
    text = body.decode("utf-8", errors="ignore").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            text = str(data.get("action") or data.get("signal") or text)
    except Exception:
        pass
    lowered = text.lower()
    if "buy" in lowered or "long" in lowered or "enter" in lowered:
        return "BUY"
    if "sell" in lowered or "exit" in lowered or "close" in lowered:
        return "EXIT"
    return None


@router.post("/{strategy_id}/{token}")
async def tv_signal(strategy_id: str, token: str, request: Request):
    if not hmac.compare_digest(token, hook_token(strategy_id)):
        raise HTTPException(403, "Invalid hook token")

    body = await request.body()
    action = _parse_action(body)
    if not action:
        raise HTTPException(400,
            "Couldn't read an action from the alert. Send JSON like "
            '{"action": "buy"} or {"action": "exit"}.')

    async with SessionLocal() as s:
        strat = (await s.execute(
            select(Strategy).where(Strategy.id == strategy_id)
            .order_by(desc(Strategy.version)).limit(1)
        )).scalar_one_or_none()
        if not strat:
            raise HTTPException(404, "Strategy not found")
        if strat.kind != "EQUITY_EOD":
            raise HTTPException(400,
                "External signals currently support equity (EQUITY_EOD) "
                "strategies only.")
        if strat.status != "PAPER_LIVE":
            raise HTTPException(409,
                f"Strategy is {strat.status} — promote to PAPER_LIVE to "
                "receive external signals. Signals only ever paper-trade.")

        spec = StrategySpec.model_validate(json.loads(strat.spec))
        symbol = spec.universe[0]

        from app.strategy.equity_paper_live import _ensure_run, _open_positions, _ltp
        run = await _ensure_run(s, strat)
        open_pos = await _open_positions(s, run.id)

        result: dict
        if action == "BUY":
            max_open = max(1, spec.risk.max_concurrent)
            if len(open_pos) >= max_open:
                result = {"ok": False, "reason": "max_concurrent reached"}
            else:
                price = await _ltp(symbol)
                if not price or price <= 0:
                    raise HTTPException(502, "No quote available for entry")
                qty = int((spec.risk.max_position_inr or 50_000) // price)
                if qty < 1:
                    result = {"ok": False, "reason": "position cap below one share"}
                else:
                    s.add(StrategyTrade(
                        id=str(uuid.uuid4()),
                        run_id=run.id,
                        strategy_id=strat.id,
                        strategy_version=strat.version,
                        entry_ts=datetime.utcnow(),
                        entry_signal=json.dumps({
                            "reason": "tradingview", "engine": "tv_hook",
                            "peak_close": price,
                        }),
                        legs=json.dumps([{
                            "leg_id": spec.legs[0].leg_id, "symbol": symbol,
                            "action": "BUY", "qty": qty,
                            "entry_price": round(price, 2),
                            "exit_price": None, "fees_inr": None,
                        }]),
                    ))
                    result = {"ok": True, "entered": True,
                              "qty": qty, "price": round(price, 2)}
                    try:
                        from app.digest import alert_trade_opened
                        await alert_trade_opened(strat.owner_id, strat.name,
                                                 "PAPER", symbol, qty, price)
                    except Exception:
                        pass
        else:  # EXIT
            if not open_pos:
                result = {"ok": True, "closed": 0, "reason": "nothing open"}
            else:
                price = await _ltp(symbol)
                if not price or price <= 0:
                    raise HTTPException(502, "No quote available for exit")
                from app.strategy.equity_runner import _friction_inr
                closed = 0
                for t in open_pos:
                    legs = json.loads(t.legs or "[]")
                    leg = legs[0] if legs else {}
                    entry_px = float(leg.get("entry_price") or 0)
                    qty = int(leg.get("qty") or 0)
                    fees = _friction_inr(entry_px, price, qty)
                    gross = (price - entry_px) * qty
                    leg["exit_price"] = round(price, 2)
                    leg["fees_inr"] = round(fees, 2)
                    t.legs = json.dumps([leg] + legs[1:])
                    t.exit_ts = datetime.utcnow()
                    t.exit_reason = "SIGNAL_EXIT"
                    t.gross_pnl_inr = round(gross, 2)
                    t.net_pnl_inr = round(gross - fees, 2)
                    t.pnl_pct = round((gross - fees) / (entry_px * qty) * 100, 3) \
                        if entry_px * qty else 0.0
                    closed += 1
                    try:
                        from app.digest import alert_trade_closed
                        await alert_trade_closed(strat.owner_id, strat.name,
                                                 "PAPER", symbol, "SIGNAL_EXIT",
                                                 float(t.net_pnl_inr))
                    except Exception:
                        pass
                result = {"ok": True, "closed": closed}
        await s.commit()

    from app.audit import record as _audit
    await _audit(event_type="TV_SIGNAL",
                 actor_id=strat.owner_id, actor_email=None,
                 resource_type="strategy", resource_id=strategy_id,
                 action=f"TradingView {action}",
                 meta={"action": action, **result}, request=request)
    return result


# ── Owner: fetch the webhook URL for a strategy ─────────────────────
@owner_router.get("/{strategy_id}/tv-hook")
async def get_tv_hook(strategy_id: str, request: Request):
    """Owner-only: the TradingView webhook URL for this strategy plus a
    ready-to-paste alert message."""
    user = getattr(request.state, "user", None) or {}
    owner = user.get("sub")
    async with SessionLocal() as s:
        strat = (await s.execute(
            select(Strategy).where(Strategy.id == strategy_id)
            .order_by(desc(Strategy.version)).limit(1)
        )).scalar_one_or_none()
    if not strat:
        raise HTTPException(404, "Strategy not found")
    if strat.owner_id != owner:
        raise HTTPException(403, "Only the owner can view the hook URL")

    path = f"/api/hooks/tv/{strategy_id}/{hook_token(strategy_id)}"
    return {
        "path": path,
        "note": ("Paste this URL into a TradingView alert's Webhook URL "
                 "(prefix with your Reyu domain). Message body: "
                 '{"action": "buy"} to enter, {"action": "exit"} to close. '
                 "Signals paper-trade only — never real orders."),
        "supported": strat.kind == "EQUITY_EOD",
        "requires_status": "PAPER_LIVE",
    }
