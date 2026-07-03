"""Integration test fixtures (task #81) — DB-backed money-path loops.

Run with a DISPOSABLE database, never the dev one:

    DATABASE_URL=postgresql+asyncpg://reyu:reyu@localhost:5432/reyu_test \
        python -m pytest tests/integration -q

In CI, DATABASE_URL already points at the throwaway service Postgres.
Every test module gets a schema from init_db() and truncated strategy
tables per test. If the DB is unreachable, the whole package skips —
unit tests stay runnable anywhere.

Event-loop discipline: no pytest-asyncio dependency — each test drives
its coroutine through run_async(), which executes it and disposes the
SQLAlchemy engine in the SAME loop so pooled connections never leak
across loops.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

# Guard: refuse to run against a DB that isn't explicitly a test DB.
_url = os.environ.get("DATABASE_URL", "")
if "test" not in _url.rsplit("/", 1)[-1]:
    pytest.skip(
        "integration tests need DATABASE_URL pointing at a *test* database "
        "(name containing 'test'); refusing to touch a real DB",
        allow_module_level=True,
    )


def run_async(coro):
    """Run a coroutine + dispose the engine in the same event loop."""
    async def _wrapped():
        try:
            return await coro
        finally:
            from app.db import engine
            await engine.dispose()
    return asyncio.run(_wrapped())


def _check_db() -> bool:
    async def _ping():
        from sqlalchemy import text
        from app.db import SessionLocal
        async with SessionLocal() as s:
            await s.execute(text("SELECT 1"))
    try:
        run_async(_ping())
        return True
    except Exception:
        return False


if not _check_db():
    pytest.skip("test database unreachable — skipping integration package",
                allow_module_level=True)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Create the full schema once per test session."""
    async def _init():
        from app.db import init_db
        await init_db()
    run_async(_init())


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate strategy tables before each test for isolation."""
    async def _truncate():
        from sqlalchemy import text
        from app.db import SessionLocal
        async with SessionLocal() as s:
            for t in ("strategy_trades", "strategy_runs", "strategies",
                      "user_legal_acceptance", "audit_log"):
                await s.execute(text(f"TRUNCATE TABLE {t} CASCADE"))
            await s.commit()
    run_async(_truncate())


# ── Factories ───────────────────────────────────────────────────────
def make_equity_spec(**over) -> dict:
    base = {
        "name": "IT momentum swing",
        "kind": "EQUITY_EOD",
        "universe": ["NSE:TCS-EQ"],
        "legs": [{"leg_id": "L1", "action": "BUY", "instrument_type": "EQUITY"}],
        "entry_rules": {"trigger": "SIGNAL", "conditions": [
            {"feature": "eq_ret_1d_pct", "op": ">", "value": 0.0}]},
        "exit_rules": {"tp_pct": 0.10, "sl_pct": 0.05, "time_stop_days": 40},
        "risk": {"max_concurrent": 1, "max_daily_loss_inr": 100000,
                 "max_position_inr": 100000},
    }
    base.update(over)
    return base


async def insert_strategy(spec_dict: dict, *, owner="test-owner",
                          status="DRAFT") -> str:
    import json
    from app.db import SessionLocal, Strategy
    from app.strategy.spec import StrategySpec
    spec = StrategySpec.model_validate(spec_dict)
    sid = str(uuid.uuid4())
    async with SessionLocal() as s:
        s.add(Strategy(
            id=sid, version=1, owner_id=owner,
            name=spec.name, kind=spec.kind, status=status,
            tier_required=spec.tier_required, created_by="test",
            spec=spec.model_dump_json(), tags=json.dumps(spec.tags),
        ))
        await s.commit()
    return sid


def synthetic_daily(n: int, start_px: float = 100.0, drift: float = 0.004,
                    start_ts: int = 1_760_000_000):
    """n daily bars with steady upward drift: [ts, o, h, l, c, v]."""
    out, px = [], start_px
    for i in range(n):
        o = px
        c = px * (1 + drift)
        out.append([start_ts + i * 86400, o, c * 1.01, o * 0.99, c, 1_000_000])
        px = c
    return out
