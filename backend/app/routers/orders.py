"""Fyers v3 order placement — validated against the official spec.

v3 numeric codes (https://myapi.fyers.in/docsv3#tag/Orders):
  type:  1=Limit, 2=Market, 3=Stop (SL-M), 4=Stoplimit (SL)
  side:  1=Buy, -1=Sell
  productType: CNC | INTRADAY | MARGIN | CO | BO
  validity: DAY | IOC

Validation we enforce locally before hitting Fyers:
  - F&O qty must be a positive multiple of lot_size
  - Equity qty must be >= 1
  - LIMIT / SL require limit_price > 0
  - SL / SL-M require stop_price > 0
  - BO requires take_profit + stop_loss
  - Indices (`-INDEX`) are not tradable
  - limit_price / stop_price must align to tick_size
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from app.routers.user_auth import require_auth as _require_live_tier
from pydantic import BaseModel, Field
from typing import Literal

from app.fyers import client as fy
from app.fyers.symbols import resolve, SymbolInfo

router = APIRouter()

ORDER_TYPE = {"LIMIT": 1, "MARKET": 2, "SL-M": 3, "SL": 4}
SIDE = {"BUY": 1, "SELL": -1}


class OrderRequest(BaseModel):
    symbol: str
    qty: int = Field(..., gt=0, description="Multiple of lot_size for F&O, >=1 for equity")
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT", "SL", "SL-M"] = "MARKET"
    product: Literal["INTRADAY", "CNC", "MARGIN", "BO", "CO"] = "INTRADAY"
    limit_price: float = 0
    stop_price: float = 0
    take_profit: float = 0          # BO only
    stop_loss: float = 0            # BO only
    validity: Literal["DAY", "IOC"] = "DAY"
    disclosed_qty: int = 0
    offline_order: bool = False
    dry_run: bool = True


def _round_to_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return price
    return round(round(price / tick) * tick, 2)


def _validate(req: OrderRequest, info: SymbolInfo) -> None:
    if not info.is_tradable:
        raise HTTPException(400, f"{info.symbol} is an index — not tradable. Trade its options/futures.")

    if info.instrument in ("OPTION", "FUTURE"):
        if info.lot_size <= 0:
            raise HTTPException(
                400,
                f"Unknown lot size for {info.symbol}. Set it via Instrument table or check the underlying.",
            )
        if req.qty % info.lot_size != 0:
            raise HTTPException(
                400,
                f"qty {req.qty} must be a multiple of lot size {info.lot_size} for {info.symbol}. "
                f"Try qty={info.lot_size} ({req.qty // info.lot_size + 1} lot(s)).",
            )
    elif info.instrument == "EQUITY":
        if req.qty < 1:
            raise HTTPException(400, "Equity qty must be >= 1")
        if req.product not in ("INTRADAY", "CNC", "MARGIN", "BO", "CO"):
            raise HTTPException(400, f"Invalid product {req.product} for equity")
    # MARGIN/CO/BO restrictions
    if info.instrument == "EQUITY" and req.product == "CNC" and req.side == "SELL":
        # Selling CNC requires holdings — Fyers will check, we just warn here
        pass

    if req.order_type in ("LIMIT", "SL") and req.limit_price <= 0:
        raise HTTPException(400, f"{req.order_type} order requires limit_price > 0")
    if req.order_type in ("SL", "SL-M") and req.stop_price <= 0:
        raise HTTPException(400, f"{req.order_type} order requires stop_price > 0")

    if req.product == "BO" and (req.take_profit <= 0 or req.stop_loss <= 0):
        raise HTTPException(400, "BO orders require take_profit and stop_loss")

    if info.tick_size > 0:
        for field, val in (("limit_price", req.limit_price), ("stop_price", req.stop_price)):
            if val > 0:
                rounded = _round_to_tick(val, info.tick_size)
                if abs(rounded - val) > 1e-6:
                    raise HTTPException(
                        400,
                        f"{field}={val} not aligned to tick {info.tick_size}; closest {rounded}",
                    )


@router.get("/preview")
async def preview(symbol: str, qty: int | None = None):
    """Return instrument metadata + qty validation result.

    The UI calls this before showing the order modal so we can pre-fill qty
    in correct lot multiples and warn the user before they submit.
    """
    info = await resolve(symbol)
    suggested_qty = info.lot_size if info.lot_size > 0 else 1
    valid = None
    error: str | None = None
    if qty is not None:
        try:
            _validate(
                OrderRequest(symbol=symbol, qty=qty, side="BUY", order_type="MARKET"),
                info,
            )
            valid = True
        except HTTPException as e:
            valid = False
            error = e.detail
    return {
        "symbol": info.symbol,
        "instrument": info.instrument,
        "underlying": info.underlying,
        "strike": info.strike,
        "option_type": info.option_type,
        "lot_size": info.lot_size,
        "tick_size": info.tick_size,
        "tradable": info.is_tradable,
        "suggested_qty": suggested_qty,
        "qty_valid": valid,
        "qty_error": error,
    }


@router.post("")
async def place(req: OrderRequest, user: dict = Depends(_require_live_tier)):
    # Free tier can still validate (dry-run), but live orders require a paid plan.
    if not req.dry_run and user.get("tier") == "free":
        raise HTTPException(403, "Live order placement requires the Pro or Algo plan. Upgrade in Settings → Subscription.")
    info = await resolve(req.symbol)
    _validate(req, info)

    payload = {
        "symbol": req.symbol,
        "qty": req.qty,
        "type": ORDER_TYPE[req.order_type],
        "side": SIDE[req.side],
        "productType": req.product,
        "limitPrice": _round_to_tick(req.limit_price, info.tick_size) if req.limit_price else 0,
        "stopPrice": _round_to_tick(req.stop_price, info.tick_size) if req.stop_price else 0,
        "validity": req.validity,
        "disclosedQty": req.disclosed_qty,
        "offlineOrder": req.offline_order,
        "stopLoss": req.stop_loss,
        "takeProfit": req.take_profit,
    }

    if req.dry_run:
        return {
            "dry_run": True,
            "instrument": info.instrument,
            "lot_size": info.lot_size,
            "lots": (req.qty // info.lot_size) if info.lot_size > 0 else None,
            "estimated_value": req.qty * (req.limit_price or 0),
            "would_send": payload,
        }

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


# -------- Batch placement + audit log --------
from datetime import datetime
from app.store import store
AUDIT_KEY = "orders:audit"


class BatchOrderRequest(BaseModel):
    legs: list[OrderRequest]
    label: str = ""           # e.g. "Bull Call Spread NIFTY"
    dry_run: bool = True


@router.post("/batch")
async def place_batch(req: BatchOrderRequest, user: dict = Depends(_require_live_tier)):
    if not req.dry_run and user.get("tier") == "free":
        raise HTTPException(403, "Live batch orders require the Pro or Algo plan.")
    """Place a multi-leg strategy. Each leg is validated independently. If any
    leg fails validation we return all errors and place nothing (dry-run-like)."""
    results = []
    errors = []
    for i, leg in enumerate(req.legs):
        try:
            info = await resolve(leg.symbol)
            _validate(leg, info)
        except HTTPException as e:
            errors.append({"leg": i, "symbol": leg.symbol, "error": e.detail})

    if errors:
        return {"ok": False, "errors": errors}

    placed = []
    for leg in req.legs:
        leg.dry_run = req.dry_run
        try:
            r = await place(leg)
            placed.append({"symbol": leg.symbol, "response": r})
        except HTTPException as e:
            placed.append({"symbol": leg.symbol, "error": e.detail})
            break  # stop on first error

    audit = {
        "ts": datetime.utcnow().isoformat(),
        "label": req.label, "dry_run": req.dry_run,
        "legs": [l.model_dump() for l in req.legs],
        "results": placed,
    }
    await store.r.lpush(AUDIT_KEY, __import__("json").dumps(audit, default=str))
    await store.r.ltrim(AUDIT_KEY, 0, 499)  # keep last 500

    from app import notify as _n
    ok = all("error" not in p for p in placed)
    await _n.emit("BATCH_ORDER", f"{req.label or 'batch'} — {len(req.legs)} legs · {'DRY' if req.dry_run else 'LIVE'} · {'OK' if ok else 'PARTIAL/FAIL'}")
    return {"ok": ok, "results": placed, "audit_ts": audit["ts"]}


@router.get("/audit")
async def audit_log(limit: int = 50):
    import json as _json
    raw = await store.r.lrange(AUDIT_KEY, 0, limit - 1)
    return [_json.loads(x) for x in raw]


# -------- Exit positions --------
class ExitRequest(BaseModel):
    symbols: list[str] | None = None   # None + all=True closes everything
    underlyings: list[str] | None = None  # close everything grouped under these
    all: bool = False
    product: str = "INTRADAY"
    dry_run: bool = True


def _reverse_action(net_qty: int) -> tuple[str, int]:
    return ("SELL", net_qty) if net_qty > 0 else ("BUY", -net_qty)


@router.post("/exit")
async def exit_positions(req: ExitRequest, user: dict = Depends(_require_live_tier)):
    if not req.dry_run and user.get("tier") == "free":
        raise HTTPException(403, "Live exits require the Pro or Algo plan.")
    """Builds market orders to flatten matching open positions.

    Filter precedence:
      all=True              → every netQty != 0
      symbols=[...]         → only those exact symbols
      underlyings=[...]     → all positions whose underlying scrip matches
    """
    raw = await fy.positions()
    nets = raw.get("netPositions", []) if isinstance(raw, dict) else []

    from app.fyers.symbols import parse as parse_sym

    candidates = []
    for p in nets:
        sym = p.get("symbol")
        net_qty = int(p.get("netQty") or 0)
        if not sym or net_qty == 0:
            continue
        under = parse_sym(sym).underlying or sym
        if req.all:
            keep = True
        elif req.symbols:
            keep = sym in req.symbols
        elif req.underlyings:
            keep = under in req.underlyings
        else:
            keep = False
        if keep:
            candidates.append((sym, net_qty, float(p.get("ltp") or 0)))

    if not candidates:
        return {"ok": True, "matched": 0, "results": [], "note": "no matching open positions"}

    placed = []
    for sym, net_qty, ltp in candidates:
        action, qty = _reverse_action(net_qty)
        leg = OrderRequest(symbol=sym, qty=qty, side=action,  # type: ignore
                           order_type="MARKET", product=req.product, dry_run=req.dry_run)
        try:
            r = await place(leg)
            placed.append({"symbol": sym, "qty": qty, "side": action, "ltp": ltp, "response": r})
        except HTTPException as e:
            placed.append({"symbol": sym, "error": e.detail})

    audit = {"ts": datetime.utcnow().isoformat(), "label": "EXIT",
             "dry_run": req.dry_run, "legs": [], "results": placed}
    await store.r.lpush(AUDIT_KEY, __import__("json").dumps(audit, default=str))
    await store.r.ltrim(AUDIT_KEY, 0, 499)

    from app import notify as _n
    ok = all("error" not in p for p in placed)
    await _n.emit("EXIT_POSITIONS",
                  f"{len(candidates)} legs · {'DRY' if req.dry_run else 'LIVE'} · {'OK' if ok else 'PARTIAL'}")

    # Compliance audit — LIVE exits always logged; DRY still recorded
    # so we can see what someone validated even if it never fired.
    from app.audit import record as _audit
    await _audit(
        event_type="ORDER_EXIT_LIVE" if not req.dry_run else "ORDER_EXIT_DRY",
        actor_id=user.get("sub"),
        actor_email=user.get("email"),
        resource_type="order",
        resource_id=None,
        action=f"{len(candidates)} legs · {'DRY' if req.dry_run else 'LIVE'} · {'OK' if ok else 'PARTIAL'}",
        meta={"legs": [c[0] for c in candidates], "ok": ok},
    )
    return {"ok": ok, "matched": len(candidates), "results": placed}
