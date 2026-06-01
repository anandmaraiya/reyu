from fastapi import APIRouter, Query
from app.fyers import client as fy
from app.analytics.chain import normalize_chain, trade_bias

router = APIRouter()


@router.get("/chain")
async def get_chain(symbol: str = Query(...), strikecount: int = 25):
    raw = await fy.option_chain(symbol, strikecount)
    chain = normalize_chain(raw)
    chain["bias"] = trade_bias(chain["summary"])
    return chain


@router.get("/quotes")
async def get_quotes(symbols: str = Query(..., description="comma-separated")):
    return await fy.quotes(symbols.split(","))
