"""Paper-trading environment for the bandit trader.

Open: pick the ATM strike of the matching option side (CE for LONG, PE for
SHORT — i.e. we BUY a directional option either way) and record entry
premium. Target = entry × 1.10, Stop = entry × 0.95.

Close: a separate sweeper polls open trades every minute. On a TP/SL hit
it books the reward (+1 / -0.5). At session close any still-OPEN trade is
booked at the current premium with reward 0 and status TIMEOUT.

`enter_trade` is paper-only by default. Setting `paper=False` would route
the buy through `fy.place_order` but we KEEP this disabled in code paths
the scheduler touches — only the API endpoint flips it (Pro/Algo tier only).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import RLTrade, OptionSnapshot
from app.fyers import client as fy
from app.analytics.chain import normalize_chain

log = logging.getLogger("reyu.rl.env")
IST = timezone(timedelta(hours=5, minutes=30))

TP_MULTIPLIER = 1.10
SL_MULTIPLIER = 0.95
REWARD_TP = 1.0
REWARD_SL = -0.5         # 2:1 R/R asymmetry — winners reward twice as much as losers cost
REWARD_TIMEOUT = 0.0


def _pick_atm_leg(chain: dict, side: str) -> dict | None:
    """side: 'CE' for LONG, 'PE' for SHORT.  Returns {symbol, strike, ltp}."""
    summary = chain["summary"]
    atm = summary.get("atm_strike")
    if not atm:
        return None
    row = next((r for r in chain["strikes"] if r["strike"] == atm), None)
    if not row:
        return None
    leg = row.get(side.lower())
    if not leg or not leg.get("symbol") or not leg.get("ltp"):
        return None
    return {"symbol": leg["symbol"], "strike": atm, "ltp": float(leg["ltp"]),
            "option_type": side}


async def enter_trade(
    s: AsyncSession,
    underlying: str,
    action: str,                 # 'LONG' | 'SHORT'
    features: list[float],
    action_logprob: float,
    qty: int = 1,
    paper: bool = True,
) -> RLTrade | None:
    """Open one paper trade. Returns the new RLTrade row, or None if the
    chain can't supply an ATM leg right now."""
    if action not in ("LONG", "SHORT"):
        return None
    side = "CE" if action == "LONG" else "PE"
    raw = await fy.option_chain(underlying, 25)
    chain = normalize_chain(raw)
    leg = _pick_atm_leg(chain, side)
    if not leg:
        return None
    entry = leg["ltp"]
    trade = RLTrade(
        id=str(uuid.uuid4()),
        underlying=underlying,
        leg_symbol=leg["symbol"],
        action=action,
        strike=leg["strike"],
        option_type=side,
        qty=qty,
        entry_premium=entry,
        target_premium=round(entry * TP_MULTIPLIER, 2),
        stop_premium=round(entry * SL_MULTIPLIER, 2),
        features=json.dumps(features),
        paper=paper,
        action_logprob=action_logprob,
    )
    s.add(trade)
    await s.commit()
    log.info("RL trade opened: %s %s @ %.2f (TP %.2f, SL %.2f) paper=%s",
             action, leg["symbol"], entry, trade.target_premium, trade.stop_premium, paper)
    return trade


async def sweep_open_trades(s: AsyncSession) -> dict[str, int]:
    """Check every OPEN trade against the current option ltp. Close if TP/SL
    hit. Times out anything still open at session close. Returns counts."""
    now_ist = datetime.utcnow().replace(tzinfo=timezone.utc).astimezone(IST)
    is_after_close = now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 30)

    open_q = select(RLTrade).where(RLTrade.status == "OPEN")
    opens = (await s.execute(open_q)).scalars().all()
    if not opens:
        return {"checked": 0, "tp": 0, "sl": 0, "timeout": 0}

    # Group by leg_symbol to batch quote calls
    by_symbol: dict[str, list[RLTrade]] = {}
    for t in opens:
        by_symbol.setdefault(t.leg_symbol, []).append(t)

    tp = sl = tout = 0
    for sym, ts_for_sym in by_symbol.items():
        try:
            q = await fy.quotes([sym])
            ltp = float((q.get("d", [{}])[0].get("v", {}) or {}).get("lp") or 0)
        except Exception as e:
            log.warning("RL sweep quote failed for %s: %s", sym, e)
            continue
        if ltp <= 0:
            continue
        for t in ts_for_sym:
            status = None; reward = None
            if ltp >= t.target_premium:
                status, reward = "TP", REWARD_TP
                tp += 1
            elif ltp <= t.stop_premium:
                status, reward = "SL", REWARD_SL
                sl += 1
            elif is_after_close:
                status, reward = "TIMEOUT", REWARD_TIMEOUT
                tout += 1
            if status:
                pnl_pct = (ltp / t.entry_premium - 1.0) * 100
                await s.execute(
                    update(RLTrade).where(RLTrade.id == t.id).values(
                        status=status, exit_ts=datetime.utcnow(),
                        exit_premium=ltp, reward=reward, pnl_pct=pnl_pct,
                    )
                )
    await s.commit()
    return {"checked": len(opens), "tp": tp, "sl": sl, "timeout": tout}
