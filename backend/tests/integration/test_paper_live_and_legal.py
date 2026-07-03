"""Equity paper-live cycles + legal acceptance gate — DB-backed.

The paper-live loops move (paper) money on a schedule with nobody
watching; the legal gate is the last wall before real money. Both were
0% covered before this module."""
import json
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from tests.integration.conftest import (
    run_async, make_equity_spec, insert_strategy, synthetic_daily,
)


def _candles_ending_today(n=60, drift=0.004):
    """Synthetic dailies whose LAST bar lands on today (IST-ish)."""
    import time
    today_start = int(time.time()) - (int(time.time()) % 86400) + 5 * 3600
    return synthetic_daily(n, start_ts=today_start - (n - 1) * 86400,
                           drift=drift)


class TestEquityPaperLiveCycles:
    def test_morning_entry_and_eod_hold(self, monkeypatch):
        candles = _candles_ending_today()

        async def fake_fetch(symbol, f, t, min_days=30):
            return candles, "SYNTHETIC"
        async def fake_ltp(symbol):
            return candles[-1][1]                     # today's open
        import app.strategy.equity_paper_live as epl
        monkeypatch.setattr(epl, "fetch_daily_candles", fake_fetch)
        monkeypatch.setattr(epl, "_ltp", fake_ltp)

        async def scenario():
            sid = await insert_strategy(make_equity_spec(), status="PAPER_LIVE")

            res = await epl.morning_cycle()
            assert res["scanned"] == 1
            assert res["entered"] == 1, res

            from app.db import SessionLocal, StrategyRun, StrategyTrade
            async with SessionLocal() as s:
                run = (await s.execute(
                    select(StrategyRun).where(StrategyRun.strategy_id == sid)
                )).scalar_one()
                assert run.mode == "PAPER" and run.status == "RUNNING"
                trade = (await s.execute(
                    select(StrategyTrade).where(StrategyTrade.run_id == run.id)
                )).scalar_one()
                assert trade.exit_ts is None
                leg = json.loads(trade.legs)[0]
                assert leg["qty"] >= 1

            # Re-running the morning must NOT double-enter (max_concurrent=1)
            res2 = await epl.morning_cycle()
            assert res2["entered"] == 0

            # Gentle up-day at EOD → position stays open, peak rolls
            res3 = await epl.eod_manage_cycle()
            assert res3["managed"] == 1 and res3["closed"] == 0

        run_async(scenario())

    def test_eod_stop_loss_closes_position(self, monkeypatch):
        candles = _candles_ending_today()
        # Crash today: low 20% under open → breaches the 5% SL
        ts, o, h, l, c, v = candles[-1]
        candles[-1] = [ts, o, o * 1.001, o * 0.80, o * 0.82, v]

        async def fake_fetch(symbol, f, t, min_days=30):
            return candles, "SYNTHETIC"
        async def fake_ltp(symbol):
            return o
        import app.strategy.equity_paper_live as epl
        monkeypatch.setattr(epl, "fetch_daily_candles", fake_fetch)
        monkeypatch.setattr(epl, "_ltp", fake_ltp)

        async def scenario():
            sid = await insert_strategy(make_equity_spec(), status="PAPER_LIVE")
            assert (await epl.morning_cycle())["entered"] == 1
            res = await epl.eod_manage_cycle()
            assert res["closed"] == 1

            from app.db import SessionLocal, StrategyTrade
            async with SessionLocal() as s:
                t = (await s.execute(select(StrategyTrade))).scalars().first()
            assert t.exit_reason == "SL"
            assert t.net_pnl_inr < 0
            leg = json.loads(t.legs)[0]
            assert leg["exit_price"] is not None
            assert leg["fees_inr"] > 0

        run_async(scenario())

    def test_intraday_cycle_skips_equity_kind(self, monkeypatch):
        """The 60s options loop must never pick up EQUITY_EOD strategies."""
        async def scenario():
            await insert_strategy(make_equity_spec(), status="PAPER_LIVE")
            import app.strategy.paper_live as pl
            monkeypatch.setattr(pl, "is_trading_hours", lambda: True)
            res = await pl.cycle()
            assert res.get("scanned", 0) == 0

        run_async(scenario())


class TestLegalGate:
    def test_pending_docs_raise_451(self):
        from fastapi import HTTPException
        from app.routers.legal import require_acceptance
        from app.legal import PLATFORM_DOCS, LIVE_DOCS

        async def scenario():
            uid = str(uuid.uuid4())
            with pytest.raises(HTTPException) as exc:
                await require_acceptance(uid, PLATFORM_DOCS + LIVE_DOCS)
            assert exc.value.status_code == 451
            pending = exc.value.detail["legal_pending"]
            assert {d["doc_type"] for d in pending} == set(PLATFORM_DOCS + LIVE_DOCS)

        run_async(scenario())

    def test_acceptance_clears_gate_and_version_bump_reopens(self):
        from fastapi import HTTPException
        from app.routers.legal import require_acceptance
        from app.legal import LIVE_DOCS, current_version
        from app.db import SessionLocal, UserLegalAcceptance

        async def scenario():
            uid = str(uuid.uuid4())
            async with SessionLocal() as s:
                for dt in LIVE_DOCS:
                    s.add(UserLegalAcceptance(
                        user_id=uid, doc_type=dt,
                        version=current_version(dt)))
                await s.commit()
            # current version accepted → passes silently
            await require_acceptance(uid, LIVE_DOCS)

            # simulate an OLD acceptance only → still gated
            uid2 = str(uuid.uuid4())
            async with SessionLocal() as s:
                for dt in LIVE_DOCS:
                    s.add(UserLegalAcceptance(
                        user_id=uid2, doc_type=dt,
                        version=current_version(dt) - 1))
                await s.commit()
            with pytest.raises(HTTPException) as exc:
                await require_acceptance(uid2, LIVE_DOCS)
            assert exc.value.status_code == 451

        run_async(scenario())
