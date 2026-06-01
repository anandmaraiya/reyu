"""Multi-portfolio management.

A portfolio is a named bag of option/equity legs. We aggregate Greeks and
check against risk caps so the UI can flag over-exposed books at a glance.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal

from app.config import settings
from app.store import store
from app.fyers import client as fy

router = APIRouter()
PF_KEY = "portfolios"


class Leg(BaseModel):
    symbol: str
    action: Literal["BUY", "SELL"]
    qty: int
    entry_price: float
    delta: float = 0
    gamma: float = 0
    theta: float = 0
    vega: float = 0


class Portfolio(BaseModel):
    name: str
    style: Literal["SCALP", "SWING", "HEDGED"] = "HEDGED"
    capital: float = 100000
    legs: list[Leg] = []


def _sign(action: str) -> int:
    return 1 if action == "BUY" else -1


def _aggregate(p: Portfolio) -> dict:
    g = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "exposure": 0.0}
    for l in p.legs:
        s = _sign(l.action)
        g["delta"] += s * l.delta * l.qty
        g["gamma"] += s * l.gamma * l.qty
        g["theta"] += s * l.theta * l.qty
        g["vega"] += s * l.vega * l.qty
        g["exposure"] += abs(l.entry_price * l.qty)
    violations = []
    if abs(g["delta"]) > settings.portfolio_max_delta:
        violations.append(f"delta {g['delta']:.0f} exceeds cap {settings.portfolio_max_delta}")
    if abs(g["vega"]) > settings.portfolio_max_vega:
        violations.append(f"vega {g['vega']:.0f} exceeds cap {settings.portfolio_max_vega}")
    if g["exposure"] > p.capital * 5:
        violations.append("notional > 5x capital")
    return {"greeks": g, "violations": violations}


@router.get("")
async def list_all():
    return await store.hgetall_json(PF_KEY)


@router.put("")
async def upsert(p: Portfolio):
    payload = p.model_dump()
    payload["risk"] = _aggregate(p)
    await store.hset_json(PF_KEY, p.name, payload)
    return payload


@router.delete("/{name}")
async def delete(name: str):
    await store.hdel(PF_KEY, name)
    return {"ok": True}


@router.post("/{name}/kill")
async def kill_switch(name: str, dry_run: bool = True):
    """Close every leg by sending opposite-side MARKET orders."""
    all_p = await store.hgetall_json(PF_KEY)
    raw = all_p.get(name)
    if not raw:
        raise HTTPException(404, "portfolio not found")
    closes = []
    for l in raw.get("legs", []):
        closes.append({
            "symbol": l["symbol"],
            "qty": l["qty"],
            "side": "SELL" if l["action"] == "BUY" else "BUY",
            "order_type": "MARKET",
            "product": "INTRADAY",
            "dry_run": dry_run,
        })
    if not dry_run:
        from app.fyers import client as fy
        for c in closes:
            try:
                await fy.place_order({
                    "symbol": c["symbol"], "qty": c["qty"],
                    "type": 2, "side": 1 if c["side"] == "BUY" else -1,
                    "productType": "INTRADAY", "limitPrice": 0, "stopPrice": 0,
                    "validity": "DAY", "disclosedQty": 0, "offlineOrder": False,
                })
            except Exception as e:
                c["error"] = str(e)
    return {"closes": closes, "dry_run": dry_run}


@router.get("/{name}/metrics")
async def metrics(name: str, minutes: int = 1440):
    from app.analytics.portfolio_metrics import metrics_for_legs
    all_p = await store.hgetall_json(PF_KEY)
    raw = all_p.get(name)
    if not raw:
        raise HTTPException(404, "portfolio not found")
    return await metrics_for_legs(raw.get("legs", []), minutes=minutes)


@router.get("/{name}/pnl")
async def live_pnl(name: str):
    all_p = await store.hgetall_json(PF_KEY)
    raw = all_p.get(name)
    if not raw:
        raise HTTPException(404, "portfolio not found")
    p = Portfolio(**{k: raw[k] for k in raw if k in Portfolio.model_fields})
    if not p.legs:
        return {"pnl": 0, "legs": []}
    q = await fy.quotes([l.symbol for l in p.legs])
    quotes = {row["symbol"]: row.get("lp", 0) for row in q.get("d", [])}
    rows = []
    total = 0.0
    for l in p.legs:
        ltp = quotes.get(l.symbol, l.entry_price)
        pnl = _sign(l.action) * (ltp - l.entry_price) * l.qty
        total += pnl
        rows.append({"symbol": l.symbol, "ltp": ltp, "entry": l.entry_price, "qty": l.qty, "pnl": pnl})
    return {"pnl": total, "legs": rows}
