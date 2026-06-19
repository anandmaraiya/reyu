"""Fyers orderBook / tradeBook / positions snapshot.

Fyers v3 SDK exposes these endpoints **CURRENT-DAY ONLY** — no historical
endpoint exists. We must snapshot at end-of-day (15:35 IST) before they
roll over, or the data is lost.

This module:
  * `snapshot_today()` — pulls all three, UPSERTs into fyers_* tables
  * Called by scheduler at 15:35 IST Mon-Fri + ad-hoc via API endpoint

Snapshot date = the trading date the data belongs to (snapshot UTC date,
adjusted to IST in the caller).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal, FyersOrder, FyersTrade, FyersPosition
from app.fyers import client as fy

log = logging.getLogger("reyu.data.fyers_sync")

IST = timezone(timedelta(hours=5, minutes=30))


def _ist_today() -> datetime:
    """Today's IST date as a naive midnight datetime (for the PK)."""
    now_ist = datetime.now(IST)
    return datetime(now_ist.year, now_ist.month, now_ist.day)


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


async def snapshot_today() -> dict:
    """Pull orderBook + tradeBook + positions and persist.

    Idempotent: re-runs the same day UPSERT the same rows.
    """
    snap_date = _ist_today()
    log.info("fyers snapshot start for %s", snap_date.date())

    if await fy.is_demo():
        return {"skipped": "demo-mode", "snapshot_date": snap_date.isoformat()}

    counts = {"orders": 0, "trades": 0, "positions": 0}

    # ── orderBook ──────────────────────────────────────────────────
    try:
        ob = await fy.orderbook()
        rows = ob.get("orderBook") or []
        if rows:
            async with SessionLocal() as s:
                for o in rows:
                    stmt = pg_insert(FyersOrder).values(
                        snapshot_date=snap_date,
                        order_id=str(o.get("id") or o.get("orderId") or ""),
                        symbol=o.get("symbol"),
                        qty=o.get("qty"),
                        filled_qty=o.get("filledQty"),
                        remaining_qty=o.get("remainingQuantity") or o.get("remainingQty"),
                        side=o.get("side"),
                        order_type=o.get("type"),
                        product_type=o.get("productType"),
                        status=o.get("status"),
                        status_message=o.get("message"),
                        limit_price=o.get("limitPrice"),
                        stop_price=o.get("stopPrice"),
                        avg_price=o.get("tradedPrice") or o.get("avgPrice"),
                        order_ts=_parse_ts(o.get("orderDateTime") or o.get("orderTime")),
                        raw=json.dumps(o, default=str),
                    ).on_conflict_do_update(
                        index_elements=[FyersOrder.snapshot_date, FyersOrder.order_id],
                        set_={
                            "status": pg_insert(FyersOrder).excluded.status,
                            "filled_qty": pg_insert(FyersOrder).excluded.filled_qty,
                            "remaining_qty": pg_insert(FyersOrder).excluded.remaining_qty,
                            "avg_price": pg_insert(FyersOrder).excluded.avg_price,
                            "raw": pg_insert(FyersOrder).excluded.raw,
                        },
                    )
                    await s.execute(stmt)
                await s.commit()
            counts["orders"] = len(rows)
    except Exception as e:
        log.exception("orderbook snapshot failed: %s", e)

    # ── tradeBook ──────────────────────────────────────────────────
    try:
        tb = await fy.tradebook()
        rows = tb.get("tradeBook") or []
        if rows:
            async with SessionLocal() as s:
                for t in rows:
                    stmt = pg_insert(FyersTrade).values(
                        snapshot_date=snap_date,
                        order_id=str(t.get("orderNumber") or t.get("id") or ""),
                        trade_number=str(t.get("tradeNumber") or t.get("orderNumber") or ""),
                        symbol=t.get("symbol"),
                        qty=t.get("tradedQty") or t.get("qty"),
                        side=t.get("side"),
                        price=t.get("tradePrice") or t.get("price"),
                        product_type=t.get("productType"),
                        trade_value=t.get("tradeValue"),
                        exchange_order_no=t.get("exchangeOrderNo"),
                        trade_ts=_parse_ts(t.get("orderDateTime") or t.get("tradeTime")),
                        raw=json.dumps(t, default=str),
                    ).on_conflict_do_nothing()
                    await s.execute(stmt)
                await s.commit()
            counts["trades"] = len(rows)
    except Exception as e:
        log.exception("tradebook snapshot failed: %s", e)

    # ── positions ──────────────────────────────────────────────────
    try:
        pb = await fy.positions()
        rows = pb.get("netPositions") or []
        if rows:
            async with SessionLocal() as s:
                for p in rows:
                    stmt = pg_insert(FyersPosition).values(
                        snapshot_date=snap_date,
                        symbol=p.get("symbol") or "",
                        product_type=p.get("productType") or "",
                        net_qty=p.get("netQty"),
                        buy_qty=p.get("buyQty"),
                        sell_qty=p.get("sellQty"),
                        buy_avg=p.get("buyAvg"),
                        sell_avg=p.get("sellAvg"),
                        realized_pnl=p.get("realized_profit") or p.get("realisedProfit"),
                        unrealized_pnl=p.get("unrealized_profit") or p.get("unrealisedProfit"),
                        ltp=p.get("ltp"),
                        raw=json.dumps(p, default=str),
                    ).on_conflict_do_update(
                        index_elements=[FyersPosition.snapshot_date,
                                        FyersPosition.symbol, FyersPosition.product_type],
                        set_={
                            "net_qty": pg_insert(FyersPosition).excluded.net_qty,
                            "realized_pnl": pg_insert(FyersPosition).excluded.realized_pnl,
                            "unrealized_pnl": pg_insert(FyersPosition).excluded.unrealized_pnl,
                            "ltp": pg_insert(FyersPosition).excluded.ltp,
                            "raw": pg_insert(FyersPosition).excluded.raw,
                        },
                    )
                    await s.execute(stmt)
                await s.commit()
            counts["positions"] = len(rows)
    except Exception as e:
        log.exception("positions snapshot failed: %s", e)

    log.info("fyers snapshot done: %s", counts)
    return {"snapshot_date": snap_date.isoformat(), **counts}
