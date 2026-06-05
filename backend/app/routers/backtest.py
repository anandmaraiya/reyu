"""
Backtest API router.

POST /api/backtest/run  — run a backtest
GET  /api/backtest/templates  — list available strategy templates for backtesting
"""
from __future__ import annotations

from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.analytics.templates import list_templates, TEMPLATES
from app.analytics.backtest import run_backtest, serialize_result
from app.fyers import client as fy

router = APIRouter()


class BacktestRequest(BaseModel):
    template_key: str
    underlying: str = "NSE:NIFTY50-INDEX"
    start_date: str = ""       # ISO format YYYY-MM-DD; default 30 days ago
    end_date: str = ""         # ISO format YYYY-MM-DD; default today
    lots: int = 1
    width_steps: int = 2
    wing_steps: int = 2
    strikecount: int = 21
    lot_size: int = 50


@router.get("/templates")
async def backtest_templates():
    """Return strategy templates available for backtesting."""
    all_templates = list_templates()
    # Mark which ones are pre-built for backtesting
    bt_keys = {"IRON_CONDOR", "LONG_STRADDLE", "SHORT_STRADDLE", "LONG_STRANGLE",
               "CALL_BUTTERFLY", "IRON_BUTTERFLY", "BULL_CALL_SPREAD", "BEAR_PUT_SPREAD"}
    for t in all_templates:
        t["backtest_ready"] = t["key"] in bt_keys
    return all_templates


@router.post("/run")
async def run_backtest_endpoint(req: BacktestRequest, request: Request):
    """Run a strategy backtest."""
    if req.template_key not in TEMPLATES:
        raise HTTPException(400, f"Unknown template: {req.template_key}. Available: {list(TEMPLATES.keys())}")

    # Default dates
    end = date.fromisoformat(req.end_date) if req.end_date else date.today()
    start = date.fromisoformat(req.start_date) if req.start_date else end - timedelta(days=30)

    if start >= end:
        raise HTTPException(400, "start_date must be before end_date")

    # Limit range to prevent timeouts
    max_days = 365
    if (end - start).days > max_days:
        raise HTTPException(400, f"Date range too large. Max {max_days} days.")

    # Determine lot size from underlying
    lot_size = req.lot_size
    if lot_size == 50:
        ul = req.underlying.upper()
        if "BANK" in ul:
            lot_size = 25
        elif "FINNIFTY" in ul:
            lot_size = 40
        elif "MIDCP" in ul:
            lot_size = 75
        elif "SENSEX" in ul:
            lot_size = 10

    is_demo = await fy.is_demo()

    result = await run_backtest(
        template_key=req.template_key,
        underlying=req.underlying,
        start_date=start,
        end_date=end,
        lots=req.lots,
        width_steps=req.width_steps,
        wing_steps=req.wing_steps,
        strikecount=req.strikecount,
        lot_size=lot_size,
        fyers_history_fn=fy.history if not is_demo else None,
        fyers_chain_fn=fy.option_chain if not is_demo else None,
        is_demo=is_demo,
    )

    return serialize_result(result)
