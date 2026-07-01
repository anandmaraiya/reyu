"""Trader P&L Journal (F-A2, P-18) + legacy free-text notes.

Two concerns in one router (both live under `/api/journal`):

1. **P&L Dashboard** — the primary consumer-facing feature. Aggregates
   the current user's strategy_trades + platform regime-router paper
   trades into totals, per-day, per-month buckets. Supports CSV export.

2. **Legacy notes** — free-text notes keyed by portfolio/strategy in
   Redis. Kept as `/api/journal/notes/*` so existing consumers don't
   break. Consider migrating to a proper table when we add
   trade-annotation UI.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.db import (
    SessionLocal, StrategyTrade, Strategy, RegimeRouterPaperTrade,
)
from app.routers.user_auth import require_user
from app.store import store

log = logging.getLogger("reyu.journal")
router = APIRouter()


# ── SECTION 1: P&L DASHBOARD ──────────────────────────────────────────
async def _fetch_user_trades(
    user_id: str,
    since: Optional[datetime] = None,
    mode_filter: Optional[str] = None,
) -> list[dict]:
    """Merge user's own strategy_trades + platform regime-router trades
    into a unified schema. Used by summary, list, and export."""
    async with SessionLocal() as s:
        # 1. User's own strategy trades — join with strategies for name/mode.
        own_q = (
            select(StrategyTrade, Strategy)
            .join(Strategy, StrategyTrade.strategy_id == Strategy.id)
            .where(Strategy.owner_id == user_id)
        )
        if since:
            own_q = own_q.where(StrategyTrade.entry_ts >= since)
        own_rows = (await s.execute(own_q)).all()

        out: list[dict] = []
        for trade, strat in own_rows:
            mode = strat.status
            if mode_filter and mode_filter.upper() not in mode:
                continue
            try:
                legs = json.loads(trade.legs or "[]")
                first_leg = legs[0] if legs else {}
                symbol = first_leg.get("symbol", "")
            except Exception:
                symbol = ""
            out.append({
                "id": trade.id,
                "date": trade.entry_ts.date().isoformat() if trade.entry_ts else None,
                "entry_ts": trade.entry_ts.isoformat() if trade.entry_ts else None,
                "exit_ts": trade.exit_ts.isoformat() if trade.exit_ts else None,
                "source": "STRATEGY",
                "strategy_name": strat.name,
                "strategy_id": strat.id,
                "mode": mode,
                "symbol": symbol,
                "entry_premium": None,
                "exit_premium": None,
                "pnl_inr": trade.net_pnl_inr,
                "pnl_pct": trade.pnl_pct,
                "status": trade.exit_reason or ("OPEN" if trade.exit_ts is None else "CLOSED"),
            })

        # 2. Platform regime-router trades — shared across all users.
        if not mode_filter or mode_filter.upper() == "PAPER":
            rr_q = select(RegimeRouterPaperTrade).where(
                RegimeRouterPaperTrade.status.in_(["TP", "SL", "OPEN", "SKIP"]),
            )
            if since:
                rr_q = rr_q.where(RegimeRouterPaperTrade.trade_date >= since.replace(tzinfo=None))
            rr_rows = (await s.execute(rr_q)).scalars().all()
            for r in rr_rows:
                out.append({
                    "id": f"rr_{r.underlying}_{r.trade_date.date().isoformat()}",
                    "date": r.trade_date.date().isoformat() if r.trade_date else None,
                    "entry_ts": r.entry_ts.isoformat() if r.entry_ts else None,
                    "exit_ts": r.exit_ts.isoformat() if r.exit_ts else None,
                    "source": "REGIME_ROUTER",
                    "strategy_name": "Regime Router (platform)",
                    "strategy_id": "regime_router",
                    "mode": "PAPER_LIVE",
                    "symbol": r.underlying,
                    "entry_premium": r.entry_premium_total,
                    "exit_premium": r.exit_premium_total,
                    "pnl_inr": r.pnl_inr,
                    "pnl_pct": None,
                    "status": r.status,
                    "regime": r.regime,
                    "action": r.action,
                })

    out.sort(key=lambda t: t.get("entry_ts") or "", reverse=True)
    return out


def _summarize(trades: list[dict]) -> dict:
    closed = [t for t in trades if t["status"] in ("TP", "SL", "TIMEOUT", "CLOSED", "MANUAL")]
    wins = [t for t in closed if (t.get("pnl_inr") or 0) > 0]
    losses = [t for t in closed if (t.get("pnl_inr") or 0) < 0]
    skips = [t for t in trades if t["status"] == "SKIP"]
    open_ = [t for t in trades if t["status"] == "OPEN"]
    total_pnl = sum((t.get("pnl_inr") or 0) for t in closed)
    return {
        "total_trades": len(trades),
        "closed": len(closed),
        "open": len(open_),
        "skipped": len(skips),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / max(1, len(closed)), 3) if closed else 0.0,
        "total_pnl_inr": round(total_pnl, 2),
        "avg_pnl_per_trade_inr": round(total_pnl / max(1, len(closed)), 2) if closed else 0.0,
        "best_pnl_inr": round(max((t.get("pnl_inr") or 0) for t in closed), 2) if closed else 0.0,
        "worst_pnl_inr": round(min((t.get("pnl_inr") or 0) for t in closed), 2) if closed else 0.0,
    }


def _bucket_by_day(trades: list[dict], days_back: int = 30) -> list[dict]:
    today = datetime.utcnow().date()
    bucket: dict = defaultdict(lambda: {"pnl_inr": 0.0, "trades": 0})
    for t in trades:
        if not t.get("date"):
            continue
        try:
            d = datetime.fromisoformat(t["date"]).date()
        except Exception:
            continue
        if (today - d).days > days_back:
            continue
        bucket[d]["pnl_inr"] += t.get("pnl_inr") or 0
        bucket[d]["trades"] += 1
    out = []
    for i in range(days_back, -1, -1):
        d = today - timedelta(days=i)
        b = bucket.get(d, {"pnl_inr": 0.0, "trades": 0})
        out.append({
            "date": d.isoformat(),
            "pnl_inr": round(b["pnl_inr"], 2),
            "trades": b["trades"],
        })
    return out


def _bucket_by_month(trades: list[dict], months_back: int = 12) -> list[dict]:
    bucket: dict = defaultdict(lambda: {"pnl_inr": 0.0, "trades": 0, "wins": 0, "losses": 0})
    for t in trades:
        if not t.get("date"):
            continue
        try:
            d = datetime.fromisoformat(t["date"]).date()
        except Exception:
            continue
        key = f"{d.year}-{d.month:02d}"
        bucket[key]["pnl_inr"] += t.get("pnl_inr") or 0
        bucket[key]["trades"] += 1
        if t["status"] == "TP" and (t.get("pnl_inr") or 0) > 0:
            bucket[key]["wins"] += 1
        elif t["status"] == "SL":
            bucket[key]["losses"] += 1
    return [
        {"month": k, **{kk: (round(vv, 2) if kk == "pnl_inr" else vv) for kk, vv in v.items()}}
        for k, v in sorted(bucket.items(), reverse=True)[:months_back]
    ]


@router.get("/summary")
async def journal_summary(
    days: int = Query(90, ge=7, le=730),
    mode: Optional[str] = Query(None, regex="^(PAPER|LIVE)$"),
    user: dict = Depends(require_user),
):
    """Full aggregate — totals, per-day (last 30d), per-month (12 mo)."""
    since = datetime.utcnow() - timedelta(days=days)
    trades = await _fetch_user_trades(user["sub"], since=since, mode_filter=mode)
    return {
        "range_days": days,
        "mode_filter": mode,
        "summary": _summarize(trades),
        "daily_pnl": _bucket_by_day(trades, days_back=min(30, days)),
        "monthly": _bucket_by_month(trades, months_back=12),
    }


@router.get("/trades")
async def journal_trades(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    mode: Optional[str] = Query(None, regex="^(PAPER|LIVE)$"),
    status: Optional[str] = Query(None, regex="^(OPEN|TP|SL|SKIP|CLOSED)$"),
    user: dict = Depends(require_user),
):
    """Paginated trade ledger."""
    since = datetime.utcnow() - timedelta(days=730)
    all_trades = await _fetch_user_trades(user["sub"], since=since, mode_filter=mode)
    if status:
        all_trades = [t for t in all_trades if t["status"] == status]
    return {
        "total": len(all_trades),
        "limit": limit,
        "offset": offset,
        "trades": all_trades[offset:offset + limit],
    }


@router.get("/export.csv")
async def journal_export(
    days: int = Query(365, ge=1, le=1825),
    user: dict = Depends(require_user),
):
    """Streamed CSV export — full trade history for the window."""
    since = datetime.utcnow() - timedelta(days=days)
    all_trades = await _fetch_user_trades(user["sub"], since=since)

    buf = io.StringIO()
    fieldnames = [
        "date", "entry_ts", "exit_ts", "source", "strategy_name",
        "mode", "symbol", "entry_premium", "exit_premium",
        "pnl_inr", "pnl_pct", "status", "regime", "action",
    ]
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for t in all_trades:
        w.writerow({k: t.get(k, "") for k in fieldnames})

    filename = f"reyu-journal-{datetime.utcnow().date().isoformat()}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── SECTION 2: LEGACY FREE-TEXT NOTES ─────────────────────────────────
# Kept for backwards compat. Consider migrating to a real table when we
# add trade-annotation UI. Mounted under /notes/* so it doesn't collide
# with the summary/trades/export routes above.
class Note(BaseModel):
    ref: str
    text: str
    tags: list[str] = []


@router.get("/notes/{ref}")
async def list_notes(ref: str, limit: int = 50):
    raw = await store.r.lrange(f"journal:{ref}", 0, limit - 1)
    return [json.loads(x) for x in raw]


@router.post("/notes")
async def add_note(n: Note):
    entry = {**n.model_dump(), "ts": datetime.utcnow().isoformat()}
    await store.r.lpush(f"journal:{n.ref}", json.dumps(entry))
    await store.r.ltrim(f"journal:{n.ref}", 0, 199)
    return entry


@router.delete("/notes/{ref}/{idx}")
async def delete_note(ref: str, idx: int):
    raw = await store.r.lrange(f"journal:{ref}", 0, -1)
    if 0 <= idx < len(raw):
        await store.r.lrem(f"journal:{ref}", 1, raw[idx])
    return {"ok": True}
