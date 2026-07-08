"""Reinforcement-learning / contextual-bandit trading endpoints.

GET    /api/rl/policies                  — list all underlyings + their model state
GET    /api/rl/policy/{underlying}       — full weights + feature names
POST   /api/rl/policy/{underlying}/reset — wipe weights, reset counters
POST   /api/rl/policy/{underlying}/toggle?on=true|false
GET    /api/rl/recommendations           — current strongest LONG/SHORT signals
GET    /api/rl/trades                    — paper-trade history (filter by status)
POST   /api/rl/decide-now                — trigger one inference cycle (debug)
POST   /api/rl/train                     — trigger training on closed trades
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, RLPolicy, RLTrade
from app.rl.features import FEATURE_NAMES, FEATURE_DIM
from app.rl.inference import decide_universe, score_universe
from app.rl.trainer import train_on_closed_trades
from app.rl.policy import Policy, ACTIONS
from app.rl.backfill import backfill_underlying, train_test_underlying
from app.fno_universe import all_high_priority
from app.fyers.master import sync_lot_sizes
from app.fyers.symbols import resolve as resolve_symbol

router = APIRouter()


@router.get("/policies")
async def list_policies(s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(RLPolicy).order_by(desc(RLPolicy.n_trades)))).scalars().all()
    return [{
        "underlying": r.underlying,
        "n_trades": r.n_trades, "n_wins": r.n_wins,
        "win_rate": round(r.n_wins / r.n_trades, 3) if r.n_trades else None,
        "cum_reward": r.cum_reward, "epsilon": r.epsilon,
        "enabled": r.enabled,
        "target_pct": r.target_pct, "stop_pct": r.stop_pct,
        "last_trained_at": r.last_trained_at.isoformat() if r.last_trained_at else None,
    } for r in rows]


@router.get("/policy/{underlying:path}")
async def get_policy(underlying: str, s: AsyncSession = Depends(get_session)):
    row = (await s.execute(select(RLPolicy).where(RLPolicy.underlying == underlying))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Policy not initialised for this underlying yet")
    pol = Policy.from_json(row.weights)
    return {
        "underlying": underlying,
        "n_trades": row.n_trades, "n_wins": row.n_wins, "cum_reward": row.cum_reward,
        "epsilon": row.epsilon, "enabled": row.enabled,
        "target_pct": row.target_pct, "stop_pct": row.stop_pct,
        "baseline": pol.baseline, "n_updates": pol.n_updates,
        "feature_names": FEATURE_NAMES,
        "w_long": pol.w_long, "w_short": pol.w_short,
        "b_long": pol.b_long, "b_short": pol.b_short,
        "feature_mean": pol.mu, "feature_std": pol.sigma,
    }


@router.post("/policies/reset-all")
async def reset_all_policies(
    confirm: bool = Query(False, description="Must be true — destructive"),
    s: AsyncSession = Depends(get_session),
):
    """Wipe every policy's weights + counters. Use after the feature
    schema changes (FEATURE_DIM bump) so the bandit retrains against the
    new layout from a clean state."""
    if not confirm:
        raise HTTPException(400, "Pass ?confirm=true to wipe all policy weights")
    res = await s.execute(update(RLPolicy).values(
        weights="{}", n_trades=0, n_wins=0, cum_reward=0.0, last_trained_at=None,
    ))
    await s.commit()
    return {"ok": True, "policies_reset": res.rowcount}


@router.post("/policy/{underlying:path}/reset")
async def reset_policy(underlying: str, s: AsyncSession = Depends(get_session)):
    row = (await s.execute(select(RLPolicy).where(RLPolicy.underlying == underlying))).scalar_one_or_none()
    if not row:
        row = RLPolicy(underlying=underlying, weights="{}", epsilon=0.10, enabled=True)
        s.add(row)
    else:
        row.weights = "{}"; row.n_trades = 0; row.n_wins = 0
        row.cum_reward = 0.0; row.last_trained_at = None
    await s.commit()
    return {"ok": True, "underlying": underlying}


@router.post("/policy/{underlying:path}/toggle")
async def toggle_policy(underlying: str, on: bool = Query(True), s: AsyncSession = Depends(get_session)):
    await s.execute(update(RLPolicy).where(RLPolicy.underlying == underlying).values(enabled=on))
    await s.commit()
    return {"ok": True, "underlying": underlying, "enabled": on}


@router.get("/recommendations")
async def recommendations(top: int = Query(20, ge=1, le=200),
                          min_conviction: float = Query(0.10, ge=0.0, le=1.0)):
    """Strongest current signals across the universe — read-only, opens no trades.

    Cached in Redis for 60s — score_universe() iterates 186 tracked symbols
    running RL inference on each (~10-14s uncached). 60s TTL means even
    a fresh page load every second of polling only hits the heavy path
    once per minute; the actual data only changes that often anyway as
    the snapshot poller is on the same 60s cadence.
    """
    import json
    from app.store import store
    cache_key = "rl:recommendations:scored_universe"

    # Try cache first — same scored universe powers any (top, min_conviction).
    scores = None
    try:
        cached = await store.r.get(cache_key)
        if cached:
            scores = json.loads(cached)
    except Exception:
        pass

    if scores is None:
        scores = await score_universe()
        try:
            await store.r.set(cache_key, json.dumps(scores), ex=60)
        except Exception:
            pass

    actionable = [s for s in scores if s["action"] != "FLAT" and s["conviction"] >= min_conviction]
    actionable.sort(key=lambda r: -r["conviction"])
    return {"count": len(actionable), "top": actionable[:top]}


@router.get("/trades")
async def list_trades(
    underlying: str | None = None,
    status: str | None = Query(None, regex="^(OPEN|TP|SL|TIMEOUT)$"),
    limit: int = Query(50, ge=1, le=500),
    s: AsyncSession = Depends(get_session),
):
    q = select(RLTrade).order_by(desc(RLTrade.entry_ts)).limit(limit)
    if underlying:
        q = q.where(RLTrade.underlying == underlying)
    if status:
        q = q.where(RLTrade.status == status)
    rows = (await s.execute(q)).scalars().all()
    return [{
        "id": r.id, "underlying": r.underlying,
        "action": r.action, "leg_symbol": r.leg_symbol,
        "strike": r.strike, "option_type": r.option_type,
        "entry_ts": r.entry_ts.isoformat() if r.entry_ts else None,
        "entry_premium": r.entry_premium, "target_premium": r.target_premium, "stop_premium": r.stop_premium,
        "exit_ts": r.exit_ts.isoformat() if r.exit_ts else None,
        "exit_premium": r.exit_premium,
        "status": r.status, "reward": r.reward, "pnl_pct": r.pnl_pct,
        "paper": r.paper,
    } for r in rows]


@router.get("/summary")
async def summary(s: AsyncSession = Depends(get_session)):
    """Universe-wide health stats."""
    total_policies = (await s.execute(select(func.count()).select_from(RLPolicy))).scalar() or 0
    enabled = (await s.execute(select(func.count()).select_from(RLPolicy).where(RLPolicy.enabled.is_(True)))).scalar() or 0
    open_trades = (await s.execute(select(func.count()).select_from(RLTrade).where(RLTrade.status == "OPEN"))).scalar() or 0
    total_trades = (await s.execute(select(func.count()).select_from(RLTrade))).scalar() or 0
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    todays_trades = (await s.execute(
        select(func.count()).select_from(RLTrade).where(RLTrade.entry_ts >= today)
    )).scalar() or 0
    todays_reward = (await s.execute(
        select(func.coalesce(func.sum(RLTrade.reward), 0)).where(
            RLTrade.entry_ts >= today, RLTrade.reward.is_not(None))
    )).scalar() or 0
    return {
        "policies": total_policies, "enabled": enabled,
        "open_trades": open_trades, "total_trades": total_trades,
        "todays_trades": todays_trades, "todays_cum_reward": float(todays_reward),
        "feature_dim": FEATURE_DIM,
    }


@router.post("/decide-now")
async def decide_now(symbols: list[str] | None = None):
    """Force one inference cycle right now (debug)."""
    res = await decide_universe(symbols=symbols, paper=True)
    return {"ran": len(res), "results": res}


@router.post("/train")
async def trigger_train(s: AsyncSession = Depends(get_session)):
    res = await train_on_closed_trades(s)
    return {"updated": res}


@router.patch("/policy/{underlying:path}/brackets")
async def set_brackets(
    underlying: str,
    target_pct: float = Query(..., gt=0, lt=2.0),
    stop_pct: float = Query(..., gt=0, lt=2.0),
    min_conviction: float | None = Query(None, ge=0.0, le=0.9,
        description="Optional — greedy-mode FLAT filter threshold"),
    s: AsyncSession = Depends(get_session),
):
    """Update the policy's target / stop percentages and (optionally) the
    live conviction filter."""
    row = (await s.execute(select(RLPolicy).where(RLPolicy.underlying == underlying))).scalar_one_or_none()
    if not row:
        row = RLPolicy(underlying=underlying, weights="{}", epsilon=0.10, enabled=True,
                       target_pct=target_pct, stop_pct=stop_pct,
                       min_conviction=min_conviction or 0.0)
        s.add(row)
    else:
        row.target_pct = target_pct
        row.stop_pct = stop_pct
        if min_conviction is not None:
            row.min_conviction = min_conviction
    await s.commit()
    return {"ok": True, "underlying": underlying,
            "target_pct": target_pct, "stop_pct": stop_pct,
            "min_conviction": row.min_conviction}


@router.post("/train-and-save")
async def train_and_save(
    underlying: str = Query(...),
    total_days: int = Query(365, ge=30, le=365),
    target_pct: float = Query(0.25, gt=0, lt=2),
    stop_pct: float = Query(0.15, gt=0, lt=2),
    min_conviction: float = Query(0.05, ge=0.0, le=0.9),
    lr: float = Query(0.10, gt=0, lt=1),
    epochs: int = Query(1, ge=1, le=20),
    weight_decay: float = Query(0.0, ge=0.0, le=0.1),
    s: AsyncSession = Depends(get_session),
):
    """Train the policy on the full window (no test split — every day
    contributes to weights), then persist brackets + conviction so live
    inference uses this exact config. Use this as the 'go-live' switch."""
    # Use train_test_underlying with test_days=2 so the test phase is
    # tiny — we only care about the trained weights being saved.
    result = await train_test_underlying(
        s, underlying, total_days=total_days, test_days=2,
        min_conviction=min_conviction,
        target_pct_override=target_pct, stop_pct_override=stop_pct,
        lr=lr, epochs=epochs, sequential=True,
        weight_decay=weight_decay,
    )
    # Persist the live-only config so inference uses these brackets / filter
    row = (await s.execute(select(RLPolicy).where(RLPolicy.underlying == underlying))).scalar_one()
    row.target_pct = target_pct
    row.stop_pct = stop_pct
    row.min_conviction = min_conviction
    row.enabled = True
    await s.commit()
    roi = getattr(result, "roi", None)
    return {
        "ok": True, "underlying": underlying,
        "train_window": result.train_window,
        "train_trades": result.train_trades,
        "train_win_rate": result.train_win_rate,
        "saved": {"target_pct": target_pct, "stop_pct": stop_pct,
                  "min_conviction": min_conviction, "lr": lr, "epochs": epochs},
        "holdout_roi": roi,
    }


@router.post("/evaluate")
async def evaluate(
    symbols: list[str],
    total_days: int = Query(30, ge=14, le=365),
    test_days: int = Query(7, ge=2, le=60),
    min_conviction: float = Query(0.0, ge=0.0, le=0.9,
        description="Force FLAT unless winning prob exceeds FLAT prob by this margin"),
    target_pct: float | None = Query(None, gt=0, lt=2,
        description="Override the policy's TP %"),
    stop_pct: float | None = Query(None, gt=0, lt=2,
        description="Override the policy's SL %"),
    target_abs: float | None = Query(None, gt=0,
        description="TP as absolute premium points (₹); overrides target_pct"),
    stop_abs: float | None = Query(None, gt=0,
        description="SL as absolute premium points (₹); overrides stop_pct"),
    lr: float | None = Query(None, gt=0, lt=1.0,
        description="Override policy learning rate (default 0.05)"),
    epochs: int = Query(1, ge=1, le=20,
        description="Number of replay passes over the training window"),
    starting_capital: float = Query(100_000, ge=10_000, le=10_000_000,
        description="Starting INR capital for ROI sim"),
    lot_size: int | None = Query(None, ge=1, le=10_000,
        description="Override lot size; if omitted the instrument table value (synced from Fyers) is used"),
    brokerage_per_trade: float = Query(50.0, ge=0.0, le=500.0,
        description="Flat per-trade cost (brokerage + STT + GST proxy)"),
    sequential: bool = Query(True,
        description="Enforce one-trade-at-a-time (matches live)"),
    weight_decay: float = Query(0.0, ge=0.0, le=0.1,
        description="L2 weight decay for policy.update (0 = no regularization)"),
    use_real_pricer: bool = Query(False,
        description="Use real intraday option premiums from option_contract_1m where available (BS fallback for gaps)"),
    s: AsyncSession = Depends(get_session),
):
    """Train/test split with optional knobs to A/B configurations.
    When `sequential=true`, only one trade is open at any time and ROI
    is computed against `starting_capital` x `lot_size` premium outlay.

    `use_real_pricer=true` reads option premiums from `option_contract_1m`
    (Fyers history backfill) for each bar; falls back to BS when the
    table has no row. Result includes a `pricer_coverage` block so you
    see real-vs-BS mix at a glance."""
    out = []
    for sym in symbols:
        eff_lot = lot_size or (await resolve_symbol(sym)).lot_size or 1
        r = await train_test_underlying(
            s, sym, total_days=total_days, test_days=test_days,
            min_conviction=min_conviction,
            target_pct_override=target_pct, stop_pct_override=stop_pct,
            lr=lr, epochs=epochs,
            starting_capital=starting_capital, lot_size=eff_lot,
            brokerage_per_trade=brokerage_per_trade,
            sequential=sequential,
            weight_decay=weight_decay,
            use_real_pricer=use_real_pricer,
            target_abs=target_abs, stop_abs=stop_abs,
        )
        out.append({
            "underlying": r.underlying,
            "train_window": r.train_window, "test_window": r.test_window,
            "train_trades": r.train_trades, "train_win_rate": r.train_win_rate,
            "train_cum_reward": r.train_cum_reward,
            "test_trades": r.test_trades, "test_win_rate": r.test_win_rate,
            "test_cum_reward": r.test_cum_reward,
            "test_cum_pnl_pct": r.test_cum_pnl_pct,
            "test_avg_pnl_per_trade_pct": r.test_avg_pnl_per_trade,
            "roi": getattr(r, "roi", None),
            "pricer_coverage": getattr(r, "pricer_coverage", None),
        })
    return {"results": out, "config": {
        "total_days": total_days, "test_days": test_days,
        "min_conviction": min_conviction,
        "target_pct": target_pct, "stop_pct": stop_pct,
        "lr": lr, "epochs": epochs,
        "starting_capital": starting_capital,
        "lot_size": lot_size, "brokerage_per_trade": brokerage_per_trade,
        "sequential": sequential,
        "use_real_pricer": use_real_pricer,
    }}


@router.post("/tune")
async def tune(
    underlying: str = Query(...,
        description="Single symbol to tune — keep small grids to respect Fyers rate limits"),
    total_days: int = Query(180, ge=30, le=365),
    test_days: int = Query(14, ge=5, le=60),
    target_pct: float = Query(0.25, gt=0, lt=2),
    stop_pct: float = Query(0.15, gt=0, lt=2),
    min_conviction: float = Query(0.05, ge=0.0, le=0.9),
    lrs: str = Query("0.01,0.025,0.05,0.10,0.20",
        description="Comma-separated LR grid"),
    epochs_grid: str = Query("1,2,4",
        description="Comma-separated epoch grid"),
    starting_capital: float = Query(100_000),
    lot_size: int | None = Query(None,
        description="Override lot; defaults to Fyers-synced instrument value"),
    brokerage_per_trade: float = Query(50.0),
    weight_decay: float = Query(0.0, ge=0.0, le=0.1,
        description="L2 weight decay for policy.update"),
    s: AsyncSession = Depends(get_session),
):
    """LR × epochs grid search. Returns all results sorted by OOS ROI %
    so you can see how the bandit responds to each setting."""
    lr_list = [float(x) for x in lrs.split(",") if x.strip()]
    ep_list = [int(x) for x in epochs_grid.split(",") if x.strip()]
    eff_lot = lot_size or (await resolve_symbol(underlying)).lot_size or 1
    grid = []
    for lr in lr_list:
        for ep in ep_list:
            r = await train_test_underlying(
                s, underlying, total_days=total_days, test_days=test_days,
                min_conviction=min_conviction,
                target_pct_override=target_pct, stop_pct_override=stop_pct,
                lr=lr, epochs=ep,
                starting_capital=starting_capital, lot_size=eff_lot,
                brokerage_per_trade=brokerage_per_trade,
                sequential=True,
                weight_decay=weight_decay,
            )
            roi = getattr(r, "roi", {}) or {}
            grid.append({
                "lr": lr, "epochs": ep,
                "train_trades": r.train_trades,
                "test_trades": r.test_trades,
                "test_win_rate": r.test_win_rate,
                "roi_pct": roi.get("roi_pct"),
                "max_dd_pct": roi.get("max_drawdown_pct"),
                "pnl_inr": roi.get("pnl_inr"),
                "trades_taken": roi.get("trades_taken"),
            })
    grid.sort(key=lambda r: (r["roi_pct"] is None, -(r["roi_pct"] or -1e9)))
    return {"underlying": underlying, "lot_size": eff_lot,
            "grid": grid, "best": grid[0] if grid else None}


@router.post("/sync-lot-sizes")
async def sync_lots():
    """Refresh per-symbol lot sizes from Fyers' public symbol-master CSV.
    Run after market hours when NSE rolls quarterly contract specs, or
    just once on a fresh deploy. Idempotent — re-running just updates."""
    res = await sync_lot_sizes()
    return {"ok": True, **res}


@router.post("/backfill")
async def backfill(
    symbols: list[str],
    days: int = Query(30, ge=1, le=180),
    reset: bool = Query(False, description="Wipe existing policy weights before training"),
    s: AsyncSession = Depends(get_session),
):
    """Pull historical 5-min candles for each symbol, simulate ATM CE/PE
    trades via Black-Scholes pricing, and run the bandit update.
    Useful for weekends / overnight bootstrapping."""
    out = []
    for sym in symbols:
        stats = await backfill_underlying(s, sym, days=days, reset_policy=reset)
        out.append({
            "underlying": stats.underlying, "sessions": stats.sessions,
            "trades": stats.trades, "wins": stats.wins, "losses": stats.losses,
            "timeouts": stats.timeouts, "cum_reward": round(stats.cum_reward, 2),
            "win_rate": round(stats.wins / stats.trades, 3) if stats.trades else None,
        })
    return {"backfilled": out}
