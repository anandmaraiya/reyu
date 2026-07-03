"""Walk-forward analysis (F-B7) — window splitting, sequential execution,
group aggregation, and the slippage override's effect on results."""
import json
from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.strategy.walkforward import (
    split_windows, start_walkforward, execute_walkforward, group_summary,
)
from tests.integration.conftest import (
    run_async, make_equity_spec, insert_strategy, synthetic_daily,
)


class TestSplitWindows:
    def test_contiguous_non_overlapping_full_cover(self):
        spans = split_windows(date(2025, 1, 1), date(2025, 12, 31), 4)
        assert len(spans) == 4
        assert spans[0][0] == date(2025, 1, 1)
        assert spans[-1][1] == date(2025, 12, 31)
        for (s1, e1), (s2, _e2) in zip(spans, spans[1:]):
            assert (s2 - e1).days == 1                # contiguous, no gap

    def test_too_short_period_rejected(self):
        with pytest.raises(ValueError, match="windows"):
            split_windows(date(2025, 1, 1), date(2025, 2, 1), 4)


class TestWalkforwardEndToEnd:
    def test_group_runs_and_stability(self, monkeypatch):
        candles = synthetic_daily(160)

        async def fake_fetch(symbol, f, t, min_days=30):
            return candles, "SYNTHETIC"
        import app.strategy.equity_runner as er
        monkeypatch.setattr(er, "fetch_daily_candles", fake_fetch)

        async def scenario():
            sid = await insert_strategy(make_equity_spec())
            start = datetime.utcfromtimestamp(candles[35][0]).date()
            end = datetime.utcfromtimestamp(candles[-1][0]).date()

            wf = await start_walkforward(
                strategy_id=sid, strategy_version=1, owner_id="test-owner",
                period_start=start, period_end=end,
                windows=3, starting_capital=100_000,
            )
            assert len(wf["run_ids"]) == 3
            await execute_walkforward(wf["run_ids"])

            summary = await group_summary(wf["group_id"], "test-owner")
            assert summary["status"] == "COMPLETED"
            assert len(summary["windows"]) == 3
            for w in summary["windows"]:
                assert w["status"] == "COMPLETED", w["error"]
                assert w["roi_pct"] is not None
            st = summary["stability"]
            assert st["windows_completed"] == 3
            assert 0.0 <= st["consistency"] <= 1.0
            assert st["roi_worst_pct"] <= st["roi_mean_pct"] <= st["roi_best_pct"]

            # Owner scoping: another user can't read the group
            assert await group_summary(wf["group_id"], "someone-else") is None

        run_async(scenario())

    def test_slippage_override_worsens_results(self, monkeypatch):
        """Sanity of the slippage model: the same strategy on the same
        data with 10× slippage must not do better."""
        candles = synthetic_daily(120)

        async def fake_fetch(symbol, f, t, min_days=30):
            return candles, "SYNTHETIC"
        import app.strategy.equity_runner as er
        monkeypatch.setattr(er, "fetch_daily_candles", fake_fetch)

        async def scenario():
            from app.strategy.runner import start_backtest_run, execute_run
            from app.db import SessionLocal, StrategyRun
            sid = await insert_strategy(make_equity_spec())
            start = datetime.utcfromtimestamp(candles[35][0]).date()
            end = datetime.utcfromtimestamp(candles[-1][0]).date()

            rois = {}
            for label, slip in (("base", None), ("heavy", 0.01)):
                params = {"period_start": start.isoformat(),
                          "period_end": end.isoformat(),
                          "starting_capital": 100_000}
                if slip is not None:
                    params["slippage_pct"] = slip
                rid = await start_backtest_run(
                    strategy_id=sid, strategy_version=1,
                    owner_id="test-owner", params=params)
                await execute_run(rid)
                async with SessionLocal() as s:
                    run = (await s.execute(select(StrategyRun)
                           .where(StrategyRun.id == rid))).scalar_one()
                assert run.status == "COMPLETED", run.error_message
                rois[label] = json.loads(run.metrics)["roi_pct"]

            assert rois["heavy"] < rois["base"]

        run_async(scenario())
