"""Paper-trading environment for the bandit trader.

Open: pick the ATM strike of the matching option side (CE for LONG, PE for
SHORT — i.e. we BUY a directional option either way) and record entry
premium. Bracket size comes from the per-policy `target_pct`/`stop_pct`
(default 20% / 20%, 1:1 R/R).

Close: a separate sweeper polls open trades every minute. On a TP/SL hit
it books the reward via `reward_for()` which scales with the bracket
asymmetry (winners +1, losers `-(stop/target)`). At session close any
still-OPEN trade is booked at the current premium with a partial reward
proportional to its realised P&L.

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

from app.db import RLTrade, RLPolicy, OptionSnapshot
from app.fyers import client as fy
from app.analytics.chain import normalize_chain

log = logging.getLogger("reyu.rl.env")
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_TARGET_PCT = 0.20
DEFAULT_STOP_PCT = 0.20


def reward_for(status: str, pnl_pct: float | None,
               target_pct: float, stop_pct: float) -> float:
    """Reward shape that scales with bracket asymmetry.

    TP hit       → +1.0
    SL hit       → -(stop_pct / target_pct)
                   (1:1 R/R → -1, 2:1 R/R → -0.5, 1:2 R/R → -2)
    TIMEOUT      → clamp(pnl_pct / target_pct, -1, +1)
                   gives a graded signal even from unfilled brackets
    """
    if status == "TP":
        return 1.0
    if status == "SL":
        return -(stop_pct / max(target_pct, 1e-6))
    if status == "TIMEOUT" and pnl_pct is not None:
        scaled = (pnl_pct / 100.0) / max(target_pct, 1e-6)
        return max(-1.0, min(1.0, scaled))
    return 0.0


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

    # Pull per-policy bracket sizes (configurable, default 20/20)
    pol_row = (await s.execute(
        select(RLPolicy).where(RLPolicy.underlying == underlying)
    )).scalar_one_or_none()
    target_pct = (pol_row.target_pct if pol_row and pol_row.target_pct else DEFAULT_TARGET_PCT)
    stop_pct = (pol_row.stop_pct if pol_row and pol_row.stop_pct else DEFAULT_STOP_PCT)

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
        target_premium=round(entry * (1.0 + target_pct), 2),
        stop_premium=round(entry * (1.0 - stop_pct), 2),
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
        # Derive each trade's TP/SL pct from its stored prices (so historical
        # trades opened before the policy's brackets changed still book
        # rewards consistent with their own bracket asymmetry)
        for t in ts_for_sym:
            status = None
            target_pct = (t.target_premium / t.entry_premium - 1.0) if t.entry_premium else DEFAULT_TARGET_PCT
            stop_pct = (1.0 - t.stop_premium / t.entry_premium) if t.entry_premium else DEFAULT_STOP_PCT
            pnl_pct = (ltp / t.entry_premium - 1.0) * 100 if t.entry_premium else 0.0
            if ltp >= t.target_premium:
                status = "TP"; tp += 1
            elif ltp <= t.stop_premium:
                status = "SL"; sl += 1
            elif is_after_close:
                status = "TIMEOUT"; tout += 1
            if status:
                reward = reward_for(status, pnl_pct, target_pct, stop_pct)
                await s.execute(
                    update(RLTrade).where(RLTrade.id == t.id).values(
                        status=status, exit_ts=datetime.utcnow(),
                        exit_premium=ltp, reward=reward, pnl_pct=pnl_pct,
                    )
                )
    await s.commit()
    return {"checked": len(opens), "tp": tp, "sl": sl, "timeout": tout}
