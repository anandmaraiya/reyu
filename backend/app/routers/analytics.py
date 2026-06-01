from fastapi import APIRouter
from pydantic import BaseModel
from typing import Literal

from app.fyers import client as fy
from app.analytics.chain import normalize_chain
from app.analytics.hedge import suggest_hedge

router = APIRouter()


class HedgeRequest(BaseModel):
    symbol: str  # underlying, e.g. NSE:NIFTY50-INDEX
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
    return suggest_hedge(
        chain,
        primary_symbol=req.primary_option_symbol,
        primary_action=req.action,
        qty=req.qty,
        target_delta=req.target_delta,
        max_cost=req.max_cost,
    )
