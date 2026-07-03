"""SEBI algo-ID registration rails (F-B1) — lifecycle + gating helper."""
from app.db import SessionLocal, AlgoRegistration
from app.routers.algo_reg import registered_algo_id
from tests.integration.conftest import run_async, make_equity_spec, insert_strategy


class TestAlgoRegistration:
    def test_gating_helper_lifecycle(self):
        async def scenario():
            sid = await insert_strategy(make_equity_spec())

            # No registration → gate closed
            assert await registered_algo_id(sid) is None

            # REQUESTED → still closed (only REGISTERED opens the gate)
            async with SessionLocal() as s:
                s.add(AlgoRegistration(strategy_id=sid, owner_id="test-owner"))
                await s.commit()
            assert await registered_algo_id(sid) is None

            # REGISTERED with an exchange ID → gate open, ID returned
            from sqlalchemy import update
            async with SessionLocal() as s:
                await s.execute(
                    update(AlgoRegistration)
                    .where(AlgoRegistration.strategy_id == sid)
                    .values(status="REGISTERED", exchange_algo_id="NSE-ALGO-42"))
                await s.commit()
            assert await registered_algo_id(sid) == "NSE-ALGO-42"

            # REJECTED → closed again
            async with SessionLocal() as s:
                await s.execute(
                    update(AlgoRegistration)
                    .where(AlgoRegistration.strategy_id == sid)
                    .values(status="REJECTED"))
                await s.commit()
            assert await registered_algo_id(sid) is None

        run_async(scenario())
