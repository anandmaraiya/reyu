"""Order placement — wraps fyersModel.place_order with a validated schema.

Fyers v3 order spec:
  qty, type (1=LIMIT, 2=MARKET, 3=SL, 4=SL-M),
  side (1=BUY, -1=SELL), productType (CNC/INTRADAY/MARGIN/BO/CO),
  limitPrice, stopPrice, validity (DAY/IOC), disclosedQty, offlineOrder.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from app.fyers import client as fy

router = APIRouter()


class OrderRequest(BaseModel):
    symbol: str
    qty: int = Field(..., gt=0)
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT", "SL", "SL-M"] = "MARKET"
    product: Literal["INTRADAY", "CNC", "MARGIN", "BO", "CO"] = "INTRADAY"
    limit_price: float = 0
    stop_price: float = 0
    validity: Literal["DAY", "IOC"] = "DAY"
    dry_run: bool = True


_TYPE = {"LIMIT": 1, "MARKET": 2, "SL": 3, "SL-M": 4}


@router.post("")
async def place(req: OrderRequest):
    payload = {
        "symbol": req.symbol,
        "qty": req.qty,
        "type": _TYPE[req.order_type],
        "side": 1 if req.side == "BUY" else -1,
        "productType": req.product,
        "limitPrice": req.limit_price,
        "stopPrice": req.stop_price,
        "validity": req.validity,
        "disclosedQty": 0,
        "offlineOrder": False,
    }
    if req.dry_run:
        return {"dry_run": True, "would_send": payload}
    try:
        resp = await fy.place_order(payload)
    except Exception as e:
        raise HTTPException(400, f"fyers rejected: {e}")
    if isinstance(resp, dict) and resp.get("s") == "error":
        raise HTTPException(400, resp.get("message", "order failed"))
    return resp


@router.get("/positions")
async def positions():
    return await fy.positions()
