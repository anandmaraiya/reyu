from fastapi import APIRouter
from pydantic import BaseModel
from typing import Literal

from app.fyers import client as fy
from app.analytics.chain import normalize_chain
from app.analytics.hedge import suggest_hedge
from app.analytics.margin import estimate as estimate_margin
from app.analytics.payoff import compute as compute_payoff

router = APIRouter()


class HedgeRequest(BaseModel):
    symbol: str
    primary_option_symbol: str
    action: Literal["BUY", "SELL"]
    qty: int = 1
    target_delta: float = 0.0
    max_cost: float | None = None
    strikecount: int = 25


@router.post("/hedge")
async def hedge(req: HedgeRequest):
    raw = await fy.option_chain(req.symbol, req.strikecount)
    chain = normalize_chain(raw)
    res = suggest_hedge(
        chain,
        primary_symbol=req.primary_option_symbol,
        primary_action=req.action,
        qty=req.qty,
        target_delta=req.target_delta,
        max_cost=req.max_cost,
    )
    if "legs" not in res:
        return res

    # Enrich with margin + payoff so the UI can render in one round-trip
    legs_for_margin = [
        {"symbol": l.get("symbol") or "", "action": l["action"], "qty": l["qty"],
         "price": l.get("ltp", 0)}
        for l in res["legs"]
    ]
    payoff_legs = [
        {
            "symbol": l.get("symbol") or f"K{l['strike']}{l['side'].upper()}",
            "instrument": "OPTION",
            "strike": l["strike"],
            "option_type": l["side"].upper(),
            "action": l["action"],
            "qty": l["qty"],
            "price": l.get("ltp", 0),
            "delta": l.get("delta"), "gamma": l.get("gamma"),
            "theta": l.get("theta"), "vega": l.get("vega"),
        }
        for l in res["legs"]
    ]
    res["payoff"] = compute_payoff(payoff_legs, spot=chain["ltp"], range_pct=0.08)
    legs_with_meta = [
        {**lm, "instrument": "OPTION", "option_type": pl.get("option_type"),
         "strike": pl.get("strike")}
        for lm, pl in zip(legs_for_margin, payoff_legs)
    ]
    res["margin"] = await estimate_margin(legs_with_meta, payoff=res["payoff"], spot=chain["ltp"])
    return res
