"""Walk-forward analysis (F-B7) — rolling out-of-sample windows.

reyu strategies are fixed-rule (the user picked the parameters), so
"walk-forward" here is the honest variant for that world: split the
period into N contiguous windows, run the SAME strategy independently
in each, and report the dispersion. A strategy that only works in one
regime shows up immediately as one great window and N-1 duds — that's
the overfitting signal a single full-period backtest hides.

Storage: each window is a normal StrategyRun (mode=BACKTEST) whose
params carry {"walkforward_group": <gid>, "walkforward_window": i}.
No new tables; runs render in the existing Runs tab, and the group
summary aggregates them.

Compliance note: the stability report states dispersion facts
(profitable-window count, ROI spread, worst window). It does not score,
rank, or pass/fail a strategy — the user judges.
"""
from __future__ import annotations

import json
import logging
import statistics
import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.db import SessionLocal, StrategyRun
from app.strategy.runner import start_backtest_run, execute_run

log = logging.getLogger("reyu.strategy.walkforward")

MIN_WINDOW_DAYS = 20          # calendar days; smaller windows are noise


def split_windows(period_start: date, period_end: date,
                  n: int) -> list[tuple[date, date]]:
    """N contiguous, non-overlapping [start, end] windows covering the
    period. Raises if windows would be shorter than MIN_WINDOW_DAYS."""
    total = (period_end - period_start).days + 1
    if total < n * MIN_WINDOW_DAYS:
        raise ValueError(
            f"{total} days can't support {n} windows of ≥{MIN_WINDOW_DAYS} "
            f"days — use a longer period or fewer windows")
    size = total // n
    out = []
    cur = period_start
    for i in range(n):
        end = period_end if i == n - 1 else cur + timedelta(days=size - 1)
        out.append((cur, end))
        cur = end + timedelta(days=1)
    return out


async def start_walkforward(
    *, strategy_id: str, strategy_version: int, owner_id: str,
    period_start: date, period_end: date, windows: int,
    starting_capital: float, slippage_pct: float | None = None,
) -> dict:
    """Create one BACKTEST run per window, tagged with a shared group id.
    Returns {group_id, run_ids, windows}. Caller schedules
    execute_walkforward(run_ids) as a background task."""
    gid = str(uuid.uuid4())
    spans = split_windows(period_start, period_end, windows)
    run_ids = []
    for i, (ws, we) in enumerate(spans):
        params = {
            "period_start": ws.isoformat(),
            "period_end": we.isoformat(),
            "starting_capital": starting_capital,
            "walkforward_group": gid,
            "walkforward_window": i,
        }
        if slippage_pct is not None:
            params["slippage_pct"] = slippage_pct
        run_ids.append(await start_backtest_run(
            strategy_id=strategy_id, strategy_version=strategy_version,
            owner_id=owner_id, params=params,
        ))
    return {
        "group_id": gid,
        "run_ids": run_ids,
        "windows": [{"window": i, "start": ws.isoformat(), "end": we.isoformat()}
                    for i, (ws, we) in enumerate(spans)],
    }


async def execute_walkforward(run_ids: list[str]) -> None:
    """Run the windows sequentially — parallel runs would hammer the
    candle source and contend on the same strategy's data."""
    for rid in run_ids:
        await execute_run(rid)


async def group_summary(group_id: str, owner_id: str) -> dict | None:
    """Aggregate a walk-forward group: per-window metrics + dispersion.
    Returns None when the group doesn't exist (or isn't the caller's)."""
    async with SessionLocal() as s:
        runs = (await s.execute(
            select(StrategyRun).where(
                StrategyRun.owner_id == owner_id,
                StrategyRun.params.like(f'%{group_id}%'),
            )
        )).scalars().all()
    if not runs:
        return None

    windows = []
    for r in sorted(runs, key=lambda r: json.loads(r.params or "{}")
                    .get("walkforward_window", 0)):
        p = json.loads(r.params or "{}")
        m = json.loads(r.metrics or "{}") if r.metrics else {}
        windows.append({
            "window": p.get("walkforward_window"),
            "start": p.get("period_start"),
            "end": p.get("period_end"),
            "run_id": r.id,
            "status": r.status,
            "roi_pct": m.get("roi_pct"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "total_trades": m.get("total_trades"),
            "win_rate": m.get("win_rate"),
            "error": r.error_message,
        })

    done = [w for w in windows if w["status"] == "COMPLETED"
            and w["roi_pct"] is not None]
    rois = [w["roi_pct"] for w in done]
    stability = None
    if len(rois) >= 2:
        stability = {
            "windows_completed": len(done),
            "windows_profitable": len([r for r in rois if r > 0]),
            "consistency": round(len([r for r in rois if r > 0]) / len(rois), 3),
            "roi_mean_pct": round(statistics.mean(rois), 2),
            "roi_std_pct": round(statistics.pstdev(rois), 2),
            "roi_best_pct": round(max(rois), 2),
            "roi_worst_pct": round(min(rois), 2),
            "worst_window_drawdown_pct": round(max(
                (w["max_drawdown_pct"] or 0) for w in done), 2),
        }

    all_done = all(w["status"] in ("COMPLETED", "ERRORED") for w in windows)
    return {
        "group_id": group_id,
        "status": "COMPLETED" if all_done else "RUNNING",
        "windows": windows,
        "stability": stability,
        "note": ("Dispersion across windows is a fact about THIS "
                 "configuration on THIS history — not a prediction. "
                 "High consistency ≠ future profitability."),
    }
