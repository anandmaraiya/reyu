"""Strategy Builder + Positions-by-ticker + templates + saved strategies."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.fyers import client as fy
from app.fyers.symbols import resolve, parse
from app.analytics.chain import normalize_chain
from app.analytics.payoff import compute as compute_payoff
from app.analytics.margin import estimate as estimate_margin
from app.analytics.templates import list_templates, apply_template
from app.analytics.pop import probability_of_profit
from app.store import store

router = APIRouter()
SAVED_KEY = "strategies"


class StrategyLeg(BaseModel):
    symbol: str
    action: Literal["BUY", "SELL"]
    qty: int
    price: float = 0
    # Optional hints from the frontend — when present they override what the
    # backend would otherwise derive from regex / chain lookup. Critical
    # because the symbol regex can mis-parse strikes for weekly Fyers
    # encodings (e.g. NSE:NIFTY2660923450CE).
    strike: float | None = None
    option_type: Literal["CE", "PE"] | None = None


class StrategyRequest(BaseModel):
    underlying: str
    legs: list[StrategyLeg]
    range_pct: float = 0.10
    points: int = 121
    strikecount: int = 25
    iv_shift_pct: float = 0       # what-if: shift IV by this many %
    dte_override_days: float | None = None


async def _enrich_legs(req_legs: list[StrategyLeg], chain: dict) -> list[dict]:
    chain_lookup: dict[str, dict] = {}
    for row in chain.get("strikes", []):
        for side in ("ce", "pe"):
            leg = row.get(side)
            if leg and leg.get("symbol"):
                chain_lookup[leg["symbol"]] = {**leg, "strike": row["strike"], "option_type": side.upper()}

    out: list[dict] = []
    for rl in req_legs:
        info = await resolve(rl.symbol)
        m = chain_lookup.get(rl.symbol, {})
        price = rl.price or m.get("ltp", 0)
        # Resolution priority:
        #   1) explicit hint from the frontend (most reliable — UI selected from chain)
        #   2) chain_lookup match (works when the chain is loaded and includes this strike)
        #   3) symbol-parser fallback (last resort, can mis-parse weekly Fyers symbols)
        strike = rl.strike if rl.strike is not None else (m.get("strike") if m.get("strike") is not None else info.strike)
        option_type = rl.option_type or m.get("option_type") or info.option_type
        out.append({
            "symbol": rl.symbol, "instrument": info.instrument,
            "strike": strike, "option_type": option_type,
            "action": rl.action, "qty": rl.qty, "price": price,
            "delta": m.get("delta"), "gamma": m.get("gamma"),
            "theta": m.get("theta"), "vega": m.get("vega"),
            "iv": m.get("iv"), "lot_size": info.lot_size,
        })
    return out


def _dte_days(expiry_ts) -> float:
    if not expiry_ts:
        return 7
    try:
        secs = int(expiry_ts) - datetime.utcnow().timestamp()
        return max(secs / 86400, 0.5)
    except Exception:
        return 7


@router.get("/templates")
async def templates():
    return list_templates()


class ApplyTemplate(BaseModel):
    key: str
    underlying: str
    lots: int = 1
    width_steps: int = 2
    wing_steps: int = 2
    strikecount: int = 25


@router.post("/template/apply")
async def template_apply(req: ApplyTemplate):
    raw = await fy.option_chain(req.underlying, req.strikecount)
    chain = normalize_chain(raw)
    legs = apply_template(req.key, chain, lots=req.lots,
                          width_steps=req.width_steps, wing_steps=req.wing_steps)
    if not legs:
        raise HTTPException(400, f"Could not build {req.key} — chain too thin")
    return {"legs": legs, "spot": chain["ltp"], "atm_strike": chain["summary"].get("atm_strike")}


@router.post("/analyse")
async def analyse(req: StrategyRequest):
    raw = await fy.option_chain(req.underlying, req.strikecount)
    chain = normalize_chain(raw)
    legs = await _enrich_legs(req.legs, chain)

    payoff = compute_payoff(legs, spot=chain["ltp"], range_pct=req.range_pct, points=req.points)
    margin = await estimate_margin(legs, payoff=payoff, spot=chain["ltp"])

    dte = req.dte_override_days if req.dte_override_days is not None else _dte_days(chain.get("expiry"))
    iv = max((chain["summary"].get("atm_iv") or 0.2) * (1 + req.iv_shift_pct / 100), 0.01)
    pop = probability_of_profit(payoff["points"], chain["ltp"], iv, dte)

    # Scenario % move table
    spot = chain["ltp"]
    scenarios = []
    if spot:
        for mv in (-10, -5, -2, 0, 2, 5, 10):
            tgt = spot * (1 + mv / 100)
            # interpolate pnl from points
            pts = payoff["points"]
            pnl = pts[0]["pnl"]
            for i in range(1, len(pts)):
                if pts[i]["S"] >= tgt:
                    a, b = pts[i - 1], pts[i]
                    pnl = a["pnl"] + (b["pnl"] - a["pnl"]) * (tgt - a["S"]) / (b["S"] - a["S"])
                    break
            scenarios.append({"move_pct": mv, "spot": round(tgt, 2), "pnl": round(pnl, 2)})

    return {
        "underlying": req.underlying, "spot": chain["ltp"],
        "chain_summary": chain.get("summary"),
        "atm_strike": chain["summary"].get("atm_strike"),
        "legs": legs, "payoff": payoff, "margin": margin,
        "pop": pop, "scenarios": scenarios, "dte_days": dte, "atm_iv": iv,
    }


# ---------- Saved strategies ----------
class SavedStrategy(BaseModel):
    name: str
    underlying: str
    view: str = "NEUTRAL"
    legs: list[StrategyLeg]
    notes: str = ""


@router.get("/saved")
async def saved_list():
    return await store.hgetall_json(SAVED_KEY)


@router.put("/saved")
async def saved_upsert(s: SavedStrategy):
    payload = s.model_dump()
    payload["saved_at"] = datetime.utcnow().isoformat()
    await store.hset_json(SAVED_KEY, s.name, payload)
    return {"ok": True}


@router.delete("/saved/{name}")
async def saved_delete(name: str):
    await store.hdel(SAVED_KEY, name)
    return {"ok": True}


# ---------- Positions-by-ticker (unchanged from before) ----------
def _underlying_of(sym: str) -> str:
    info = parse(sym)
    return info.underlying or sym.split(":")[-1].split("-")[0]


@router.get("/positions-by-ticker")
async def positions_by_ticker():
    try:
        raw = await fy.positions()
    except Exception as e:
        return {"error": str(e), "groups": []}

    nets = raw.get("netPositions", []) if isinstance(raw, dict) else []
    grouped: dict[str, list[dict]] = defaultdict(list)
    for p in nets:
        sym = p.get("symbol")
        net_qty = int(p.get("netQty") or 0)
        if not sym or net_qty == 0:
            continue
        info = await resolve(sym)
        grouped[_underlying_of(sym)].append({
            "symbol": sym, "instrument": info.instrument,
            "strike": info.strike, "option_type": info.option_type,
            "action": "BUY" if net_qty > 0 else "SELL",
            "qty": abs(net_qty),
            "price": float(p.get("netAvg") or p.get("buyAvg") or p.get("sellAvg") or 0),
            "ltp": float(p.get("ltp") or 0),
            "pl": float(p.get("pl") or 0),
        })

    # Map common F&O underlying scrips to their canonical Fyers index/equity symbol.
    # Without this the previous fallback averaged option PREMIUMS as "spot",
    # producing absurd payoff charts (e.g. NIFTY shown at 67 instead of 23,483).
    INDEX_MAP = {
        "NIFTY": "NSE:NIFTY50-INDEX",
        "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
        "FINNIFTY": "NSE:FINNIFTY-INDEX",
        "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
        "NIFTYNXT50": "NSE:NIFTYNXT50-INDEX",
        "SENSEX": "BSE:SENSEX-INDEX",
        "BANKEX": "BSE:BANKEX-INDEX",
    }

    groups = []
    for under, legs in grouped.items():
        has_option = any(l["instrument"] == "OPTION" for l in legs)
        underlying_sym = INDEX_MAP.get(under) if has_option else f"NSE:{under}-EQ"
        spot = None
        if underlying_sym:
            try:
                q = await fy.quotes([underlying_sym])
                spot = (q.get("d", [{}])[0].get("v", {}).get("lp")) if isinstance(q, dict) else None
            except Exception:
                pass
        if not spot:
            # Best fallback when we cannot fetch the underlying — use the
            # weighted-average STRIKE of the open option legs (still wrong but
            # at least lives in the right order of magnitude).
            opt_legs = [l for l in legs if l.get("strike")]
            if opt_legs:
                w = sum(l["qty"] for l in opt_legs) or 1
                spot = sum(l["strike"] * l["qty"] for l in opt_legs) / w
            else:
                spot = sum(l["ltp"] * l["qty"] for l in legs) / max(sum(l["qty"] for l in legs), 1)
        payoff = compute_payoff(legs, spot=spot, range_pct=0.10)
        margin = await estimate_margin(legs, payoff=payoff, spot=spot)

        # Adjustment suggestions
        suggestions = []
        net_delta = payoff["greeks"]["delta"]
        if abs(net_delta) > 50:
            suggestions.append({"type": "DELTA_HEDGE",
                                 "msg": f"Net Δ {net_delta:.1f} — consider hedging with futures or opposite-side options"})
        net_pl = sum(l["pl"] for l in legs)
        invested = sum(abs(l["price"] * l["qty"]) for l in legs) or 1
        if net_pl > 0.6 * invested:
            suggestions.append({"type": "TAKE_PROFIT", "msg": f"Up {net_pl/invested*100:.0f}% — consider booking partial"})
        if net_pl < -0.4 * invested:
            suggestions.append({"type": "STOP", "msg": f"Down {net_pl/invested*100:.0f}% — review stop"})

        groups.append({
            "underlying": under, "underlying_symbol": underlying_sym, "spot": spot,
            "legs": legs, "payoff": payoff, "margin": margin,
            "net_pl": round(sum(l["pl"] for l in legs), 2),
            "suggestions": suggestions,
        })

    groups.sort(key=lambda g: -abs(g["net_pl"]))
    return {"groups": groups}
