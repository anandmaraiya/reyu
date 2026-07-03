"""Full EQUITY_EOD backtest through the real persistence path — the loop
that was 0% covered by the unit suite. Candles are synthetic via
monkeypatch, so no broker dependency; everything else (run row, trade
rows, metrics JSON, status flip) is the production code path."""
import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from tests.integration.conftest import (
    run_async, make_equity_spec, insert_strategy, synthetic_daily,
)


def _period_from_candles(candles, warmup=30):
    start = datetime.utcfromtimestamp(candles[warmup][0]).date()
    end = datetime.utcfromtimestamp(candles[-1][0]).date()
    return start, end


async def _run_backtest(sid: str, period_start: date, period_end: date) -> str:
    from app.strategy.runner import start_backtest_run, execute_run
    run_id = await start_backtest_run(
        strategy_id=sid, strategy_version=1, owner_id="test-owner",
        params={"period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "starting_capital": 100_000},
    )
    await execute_run(run_id)
    return run_id


async def _get_run(run_id: str):
    from app.db import SessionLocal, StrategyRun, StrategyTrade
    async with SessionLocal() as s:
        run = (await s.execute(
            select(StrategyRun).where(StrategyRun.id == run_id))).scalar_one()
        trades = (await s.execute(
            select(StrategyTrade).where(StrategyTrade.run_id == run_id)
            .order_by(StrategyTrade.entry_ts))).scalars().all()
    return run, trades


class TestEquityBacktestEndToEnd:
    def test_signal_strategy_completes_and_persists(self, monkeypatch):
        candles = synthetic_daily(120)

        async def fake_fetch(symbol, f, t, min_days=30):
            return candles, "SYNTHETIC"
        import app.strategy.equity_runner as er
        monkeypatch.setattr(er, "fetch_daily_candles", fake_fetch)

        async def scenario():
            sid = await insert_strategy(make_equity_spec())
            start, end = _period_from_candles(candles)
            run_id = await _run_backtest(sid, start, end)
            run, trades = await _get_run(run_id)

            assert run.status == "COMPLETED", run.error_message
            metrics = json.loads(run.metrics)
            assert metrics["total_trades"] == len(trades) > 0
            assert metrics["starting_capital"] == 100_000
            curve = json.loads(run.equity_curve)
            assert curve[0]["equity"] == 100_000

            # Entries fill at the NEXT bar's open (no lookahead): every
            # trade's entry price ≈ some bar's open × (1 + slippage).
            opens = {round(c[1] * (1 + er.FRICTION["slippage_pct"]), 6)
                     for c in candles}
            for t in trades:
                leg = json.loads(t.legs)[0]
                assert any(abs(leg["entry_price"] - o) < 0.01 for o in opens)
                assert t.net_pnl_inr is not None
                assert t.exit_reason in ("TP", "SL", "TRAIL", "TIME", "EOP")

            # First completed run flips DRAFT → BACKTESTED
            from app.db import SessionLocal, Strategy
            async with SessionLocal() as s:
                strat = (await s.execute(
                    select(Strategy).where(Strategy.id == sid))).scalar_one()
            assert strat.status == "BACKTESTED"

        run_async(scenario())

    def test_sl_fires_before_tp_same_bar(self, monkeypatch):
        """Conservative-fill guarantee: a bar whose range hits both SL and
        TP must resolve to SL."""
        candles = synthetic_daily(40, drift=0.001)
        # Day 35: violent bar — low breaches SL(-5%) and high breaches TP(+10%)
        entry_ref = candles[34][1]
        candles[35] = [candles[35][0], entry_ref,
                       entry_ref * 1.30, entry_ref * 0.70, entry_ref, 1_000_000]

        async def fake_fetch(symbol, f, t, min_days=30):
            return candles, "SYNTHETIC"
        import app.strategy.equity_runner as er
        monkeypatch.setattr(er, "fetch_daily_candles", fake_fetch)

        async def scenario():
            sid = await insert_strategy(make_equity_spec())
            start, end = _period_from_candles(candles)
            run_id = await _run_backtest(sid, start, end)
            run, trades = await _get_run(run_id)
            assert run.status == "COMPLETED", run.error_message
            sl_trades = [t for t in trades if t.exit_reason == "SL"]
            assert sl_trades, "violent bar must close a position as SL"
            assert not any(t.exit_reason == "TP" and
                           t.exit_ts == sl_trades[0].exit_ts for t in trades)

        run_async(scenario())

    def test_insufficient_history_errors_cleanly(self, monkeypatch):
        async def fake_fetch(symbol, f, t, min_days=30):
            raise ValueError("insufficient daily history for TEST")
        import app.strategy.equity_runner as er
        monkeypatch.setattr(er, "fetch_daily_candles", fake_fetch)

        async def scenario():
            sid = await insert_strategy(make_equity_spec())
            run_id = await _run_backtest(sid, date(2026, 1, 1), date(2026, 6, 1))
            run, _ = await _get_run(run_id)
            assert run.status == "ERRORED"
            assert "insufficient" in (run.error_message or "")

        run_async(scenario())

    def test_schedule_sip_accumulates(self, monkeypatch):
        candles = synthetic_daily(60)

        async def fake_fetch(symbol, f, t, min_days=30):
            return candles, "SYNTHETIC"
        import app.strategy.equity_runner as er
        monkeypatch.setattr(er, "fetch_daily_candles", fake_fetch)

        async def scenario():
            sid = await insert_strategy(make_equity_spec(
                entry_rules={"trigger": "SCHEDULE",
                             "schedule": {"days": ["MON", "TUE", "WED", "THU", "FRI"],
                                          "time_window": "09:15-15:30"}},
                exit_rules={"tp_pct": 0.9, "sl_pct": 0.8, "time_stop_days": 365},
                risk={"max_concurrent": 50, "max_position_inr": 2000,
                      "max_daily_loss_inr": 1_000_000},
            ))
            start, end = _period_from_candles(candles)
            run_id = await _run_backtest(sid, start, end)
            run, trades = await _get_run(run_id)
            assert run.status == "COMPLETED", run.error_message
            # Accumulation: many tranches, all EOP-closed at period end
            assert len(trades) > 10
            assert all(t.exit_reason == "EOP" for t in trades)

        run_async(scenario())
