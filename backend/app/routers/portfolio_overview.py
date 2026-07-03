"""Portfolio overview — cross-strategy aggregation for multi-strategy users (P1b).

The per-strategy Live Monitor answers "how is THIS strategy doing"; this
router answers "how is my whole book doing" — the view an HNI running
5-10 strategies actually needs:

    GET  /api/portfolio-overview           aggregate capital, P&L, correlation
    POST /api/portfolio-overview/halt-all  global kill-switch (halts every
                                           RUNNING paper/live run, audited)

Aggregation is computed from strategy_runs + strategy_trades (the same
source of truth the journal uses) plus live MTM quotes for open legs.
Option-level Greeks aggregation is a known follow-up — this MVP reports
capital, P&L, drawdown-relevant series, and pairwise P&L correlation.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, desc

from app.db import SessionLocal, Strategy, StrategyRun, StrategyTrade
from app.routers.user_auth import require_user

log = logging.getLogger("reyu.portfolio_overview")
router = APIRouter(prefix="/api/portfolio-overview", tags=["portfolio-overview"])


@router.get("")
async def overview(user: dict = Depends(require_user)):
    owner = user["sub"]
    since_30d = datetime.utcnow() - timedelta(days=30)

    async with SessionLocal() as s:
        # Latest version of every non-archived strategy the user owns
        strats = (await s.execute(
            select(Strategy).where(
                Strategy.owner_id == owner,
                Strategy.status != "ARCHIVED",
            )
        )).scalars().all()
        latest: dict[str, Strategy] = {}
        for st in strats:
            if st.id not in latest or st.version > latest[st.id].version:
                latest[st.id] = st

        active_runs = (await s.execute(
            select(StrategyRun).where(
                StrategyRun.owner_id == owner,
                StrategyRun.mode.in_(["PAPER", "LIVE"]),
                StrategyRun.status == "RUNNING",
            )
        )).scalars().all()
        runs_by_sid: dict[str, list[StrategyRun]] = defaultdict(list)
        for r in active_runs:
            runs_by_sid[r.strategy_id].append(r)

        sids = list(latest.keys())
        trades_30d = (await s.execute(
            select(StrategyTrade).where(
                StrategyTrade.strategy_id.in_(sids or ["-"]),
                StrategyTrade.entry_ts >= since_30d,
            ).order_by(StrategyTrade.entry_ts)
        )).scalars().all()

    # Open (paper/live) legs — only from active runs, so backtest rows
    # never count as deployed capital.
    active_run_ids = {r.id for r in active_runs}
    open_trades = [t for t in trades_30d
                   if t.exit_ts is None and t.run_id in active_run_ids]

    # ── Live MTM for open legs (one quotes call) ────────────────────
    symbols = []
    leg_by_tid: dict[str, dict] = {}
    for t in open_trades:
        legs = json.loads(t.legs or "[]")
        if legs:
            leg_by_tid[t.id] = legs[0]
            if legs[0].get("symbol"):
                symbols.append(legs[0]["symbol"])
    ltp: dict[str, float] = {}
    if symbols:
        try:
            from app.fyers import client as fy
            q = await fy.quotes(list(set(symbols)))
            for item in (q.get("d") or []):
                v = item.get("v") or {}
                if v.get("lp"):
                    ltp[item.get("n")] = float(v["lp"])
        except Exception as e:
            log.warning("quotes for overview failed: %s", e)

    # ── Per-strategy rollup ──────────────────────────────────────────
    per_strategy = []
    total_deployed = total_unrealised = total_realised_30d = 0.0
    for sid, st in latest.items():
        s_open = [t for t in open_trades if t.strategy_id == sid]
        s_closed = [t for t in trades_30d
                    if t.strategy_id == sid and t.exit_ts is not None
                    and t.run_id in active_run_ids]
        deployed = unreal = 0.0
        for t in s_open:
            leg = leg_by_tid.get(t.id) or {}
            entry = float(leg.get("entry_price") or 0)
            qty = float(leg.get("qty") or 0)
            deployed += entry * qty
            cur = ltp.get(leg.get("symbol") or "")
            if cur is not None and entry:
                sign = 1 if (leg.get("action") or "BUY") == "BUY" else -1
                unreal += (cur - entry) * qty * sign
        realised = sum(t.net_pnl_inr if t.net_pnl_inr is not None
                       else (t.gross_pnl_inr or 0) for t in s_closed)
        is_active = sid in runs_by_sid
        if not (is_active or s_open or s_closed):
            continue                      # skip strategies with no live footprint
        total_deployed += deployed
        total_unrealised += unreal
        total_realised_30d += realised
        per_strategy.append({
            "strategy_id": sid,
            "name": st.name,
            "kind": st.kind,
            "status": st.status,
            "modes": sorted({r.mode for r in runs_by_sid.get(sid, [])}),
            "active_runs": len(runs_by_sid.get(sid, [])),
            "open_positions": len(s_open),
            "capital_deployed_inr": round(deployed, 2),
            "unrealised_inr": round(unreal, 2),
            "realised_30d_inr": round(realised, 2),
            "max_position_inr": _risk_cap(st),
        })

    # ── Combined + per-strategy daily P&L (closed trades, 30d) ──────
    daily: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in trades_30d:
        if t.exit_ts is None or t.run_id not in active_run_ids:
            continue
        day = t.exit_ts.date().isoformat()
        pnl = t.net_pnl_inr if t.net_pnl_inr is not None else (t.gross_pnl_inr or 0)
        daily[day][t.strategy_id] += pnl
        daily[day]["__total__"] += pnl
    days_sorted = sorted(daily)
    combined_daily = [
        {"date": d, "pnl_inr": round(daily[d]["__total__"], 2)} for d in days_sorted
    ]

    correlations = _pairwise_correlation(daily, days_sorted,
                                         [p["strategy_id"] for p in per_strategy],
                                         {p["strategy_id"]: p["name"] for p in per_strategy})

    return {
        "as_of": datetime.utcnow().isoformat(),
        "aggregate": {
            "strategies_active": len([p for p in per_strategy if p["active_runs"]]),
            "open_positions": len(open_trades),
            "capital_deployed_inr": round(total_deployed, 2),
            "unrealised_inr": round(total_unrealised, 2),
            "realised_30d_inr": round(total_realised_30d, 2),
        },
        "strategies": sorted(per_strategy,
                             key=lambda p: -p["capital_deployed_inr"]),
        "combined_daily_pnl": combined_daily,
        "correlations": correlations,
        "notes": [
            "Unrealised P&L is marked to the latest broker quote and moves with the market.",
            "Correlation uses daily closed P&L over the last 30 days — needs 10+ overlapping days to be meaningful.",
        ],
    }


def _risk_cap(st: Strategy) -> float | None:
    try:
        return (json.loads(st.spec or "{}").get("risk") or {}).get("max_position_inr")
    except Exception:
        return None


def _pairwise_correlation(
    daily: dict[str, dict[str, float]],
    days_sorted: list[str],
    sids: list[str],
    names: dict[str, str],
) -> list[dict]:
    """Pearson correlation of daily P&L for every strategy pair with
    >= 10 days where both have activity. Factual diversification info —
    not a performance ranking."""
    out = []
    for i in range(len(sids)):
        for j in range(i + 1, len(sids)):
            a, b = sids[i], sids[j]
            xs, ys = [], []
            for d in days_sorted:
                if a in daily[d] and b in daily[d]:
                    xs.append(daily[d][a]); ys.append(daily[d][b])
            if len(xs) < 10:
                continue
            n = len(xs)
            ma, mb = sum(xs) / n, sum(ys) / n
            cov = sum((x - ma) * (y - mb) for x, y in zip(xs, ys))
            va = sum((x - ma) ** 2 for x in xs)
            vb = sum((y - mb) ** 2 for y in ys)
            if va == 0 or vb == 0:
                continue
            out.append({
                "a": names.get(a, a), "b": names.get(b, b),
                "days": n,
                "correlation": round(cov / (va ** 0.5 * vb ** 0.5), 3),
            })
    return out


@router.post("/halt-all")
async def halt_all(user: dict = Depends(require_user)):
    """Global kill-switch — halts every RUNNING paper/live run the user
    owns. Open trades are marked MANUAL-exit at last known price (same
    contract as the per-run halt). Fully audited. The frontend gates this
    behind a typed 'HALT-ALL' confirmation."""
    owner = user["sub"]
    halted_runs, halted_trades = [], 0

    async with SessionLocal() as s:
        runs = (await s.execute(
            select(StrategyRun).where(
                StrategyRun.owner_id == owner,
                StrategyRun.mode.in_(["PAPER", "LIVE"]),
                StrategyRun.status == "RUNNING",
            )
        )).scalars().all()

        for run in runs:
            opens = (await s.execute(
                select(StrategyTrade).where(
                    StrategyTrade.run_id == run.id,
                    StrategyTrade.exit_ts.is_(None),
                )
            )).scalars().all()
            for t in opens:
                legs = json.loads(t.legs or "[]")
                if legs and legs[0].get("exit_price") is None:
                    legs[0]["exit_price"] = legs[0].get("entry_price")
                    t.legs = json.dumps(legs)
                t.exit_ts = datetime.utcnow()
                t.exit_reason = "MANUAL"
                t.gross_pnl_inr = t.gross_pnl_inr or 0.0
                t.pnl_pct = t.pnl_pct or 0.0
                halted_trades += 1

            run.status = "HALTED"
            run.ended_at = datetime.utcnow()
            halted_runs.append(run.id)

            strat = (await s.execute(
                select(Strategy).where(
                    Strategy.id == run.strategy_id,
                    Strategy.version == run.strategy_version,
                )
            )).scalar_one_or_none()
            if strat and strat.status in ("PAPER_LIVE", "LIVE"):
                strat.status = "BACKTESTED"
        await s.commit()

    from app.audit import record as _audit
    await _audit(
        event_type="PORTFOLIO_HALT_ALL",
        actor_id=owner, actor_email=user.get("email"),
        resource_type="portfolio", resource_id=None,
        action=f"Global kill-switch — halted {len(halted_runs)} runs, "
               f"{halted_trades} open trades closed",
        meta={"run_ids": halted_runs},
    )

    return {"ok": True, "halted_runs": len(halted_runs),
            "halted_trades": halted_trades}
