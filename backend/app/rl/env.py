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

# ── Money-based reward ──────────────────────────────────────────────
# The bandit optimises ACTUAL rupees, not an abstract bracket score. One
# reward unit = REWARD_UNIT_INR of net P&L, so a ₹1,000 winning trade earns
# +1.0 and a ₹250 win earns +0.25 — the policy naturally prefers bigger,
# cheaper-to-win money over tiny scalps. The ~1k divisor keeps the linear
# policy's gradient in a sane range (typical NIFTY 1-lot trade is a few
# hundred to a few thousand rupees).
REWARD_UNIT_INR = 1000.0

# Light round-trip friction so the policy learns AFTER costs, not gross.
_SLIPPAGE_FRAC = 0.0005      # ~5bps of turnover, entry+exit
_FLAT_COST_INR = 20.0        # brokerage/charges proxy, per trade


def trade_cost_inr(entry_prem: float, exit_prem: float, lot_size: int, qty: int = 1) -> float:
    """Round-trip cost in rupees for a single bought-option trade."""
    turnover = (abs(entry_prem) + abs(exit_prem)) * lot_size * qty
    return turnover * _SLIPPAGE_FRAC + _FLAT_COST_INR * qty


def money_reward(entry_prem: float, exit_prem: float, lot_size: int,
                 qty: int = 1, apply_cost: bool = True) -> float:
    """Reward = net rupee P&L of the trade, scaled to REWARD_UNIT_INR.

    We always BUY a directional option (CE for LONG, PE for SHORT), so the
    P&L is simply (exit − entry) × lot × qty. Lot-size aware: the same +20%
    move on a fat premium is worth more money — and more reward — than on a
    cheap one, which is exactly what we want the policy to learn."""
    gross = (exit_prem - entry_prem) * lot_size * qty
    cost = trade_cost_inr(entry_prem, exit_prem, lot_size, qty) if apply_cost else 0.0
    return (gross - cost) / REWARD_UNIT_INR


def net_pnl_inr(entry_prem: float, exit_prem: float, lot_size: int,
                qty: int = 1, apply_cost: bool = True) -> float:
    """The rupee figure behind money_reward (for reporting / trade rows)."""
    gross = (exit_prem - entry_prem) * lot_size * qty
    cost = trade_cost_inr(entry_prem, exit_prem, lot_size, qty) if apply_cost else 0.0
    return gross - cost


def reward_for(status: str, pnl_pct: float | None,
               target_pct: float, stop_pct: float) -> float:
    """LEGACY bracket-normalised reward (TP +1 / SL −ratio). Kept for
    backward-compatible callers; the RL bandit now trains on money_reward."""
    if status == "TP":
        return 1.0
    if status == "SL":
        return -(stop_pct / max(target_pct, 1e-6))
    if status == "TIMEOUT" and pnl_pct is not None:
        scaled = (pnl_pct / 100.0) / max(target_pct, 1e-6)
        return max(-1.0, min(1.0, scaled))
    return 0.0


_LOT_CACHE: dict[str, int] = {}


async def _lot_size(underlying: str) -> int:
    """Contracts per lot for the underlying — DB (Fyers-synced) first, then
    the hardcoded index map. Cached per process."""
    if underlying in _LOT_CACHE:
        return _LOT_CACHE[underlying]
    try:
        from app.fyers.symbols import resolve
        lot = (await resolve(underlying)).lot_size or 1
    except Exception:
        lot = 1
    _LOT_CACHE[underlying] = int(lot)
    return int(lot)


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
    # Absolute premium-point brackets override % when the policy has them set.
    target_abs = pol_row.target_abs if pol_row else None
    stop_abs = pol_row.stop_abs if pol_row else None

    entry = leg["ltp"]
    tp_prem = round(entry + target_abs, 2) if target_abs else round(entry * (1.0 + target_pct), 2)
    sl_prem = (round(max(entry - stop_abs, 0.05), 2) if stop_abs
               else round(entry * (1.0 - stop_pct), 2))
    trade = RLTrade(
        id=str(uuid.uuid4()),
        underlying=underlying,
        leg_symbol=leg["symbol"],
        action=action,
        strike=leg["strike"],
        option_type=side,
        qty=qty,
        entry_premium=entry,
        target_premium=tp_prem,
        stop_premium=sl_prem,
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
                lot = await _lot_size(t.underlying)
                reward = money_reward(t.entry_premium, ltp, lot, qty=t.qty or 1)
                await s.execute(
                    update(RLTrade).where(RLTrade.id == t.id).values(
                        status=status, exit_ts=datetime.utcnow(),
                        exit_premium=ltp, reward=reward, pnl_pct=pnl_pct,
                    )
                )
    await s.commit()
    return {"checked": len(opens), "tp": tp, "sl": sl, "timeout": tout}
