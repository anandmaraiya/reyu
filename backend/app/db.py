"""SQLAlchemy async DB with TimescaleDB hypertables.

Two time-series tables:
  - tick_1m: 1-min OHLCV per instrument
  - option_snapshot: aggregate option-chain metrics (PCR / OI / IV) per
    underlying+expiry, sampled every SNAPSHOT_INTERVAL_SEC
"""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Column, String, Float, BigInteger, DateTime, Integer, Index, text,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import settings

Base = declarative_base()
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Instrument(Base):
    __tablename__ = "instruments"
    symbol = Column(String, primary_key=True)        # e.g. NSE:RELIANCE-EQ
    name = Column(String)
    exch = Column(String)
    segment = Column(String)
    lot_size = Column(Integer, default=1)
    tick_size = Column(Float, default=0.05)
    expiry = Column(DateTime, nullable=True)
    strike = Column(Float, nullable=True)
    option_type = Column(String, nullable=True)      # CE/PE/NULL
    underlying = Column(String, nullable=True)
    tracked = Column(Integer, default=0)             # 1 if scheduler polls it
    tier = Column(Integer, default=2)                # 1 = high-priority (60s), 2 = low (300s)


class Tick1m(Base):
    __tablename__ = "tick_1m"
    ts = Column(DateTime, primary_key=True)
    symbol = Column(String, primary_key=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger, default=0)
    oi = Column(BigInteger, default=0)

    __table_args__ = (Index("ix_tick_1m_symbol_ts", "symbol", "ts"),)


class OptionSnapshot(Base):
    """Per-underlying option-chain summary, sampled at fixed cadence."""
    __tablename__ = "option_snapshot"
    ts = Column(DateTime, primary_key=True)
    symbol = Column(String, primary_key=True)        # underlying
    expiry = Column(DateTime, primary_key=True)
    ltp = Column(Float)
    pcr_oi = Column(Float)
    pcr_volume = Column(Float)
    max_pain = Column(Float)
    atm_strike = Column(Float)
    atm_iv = Column(Float)
    total_ce_oi = Column(BigInteger, default=0)
    total_pe_oi = Column(BigInteger, default=0)
    ce_oi_change = Column(BigInteger, default=0)
    pe_oi_change = Column(BigInteger, default=0)
    bias_score = Column(Integer, default=0)

    __table_args__ = (Index("ix_opt_snap_symbol_ts", "symbol", "ts"),)


async def init_db() -> None:
    """Create tables + promote time-series tables to Timescale hypertables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Best-effort: works on Timescale image, no-op on plain PG. Also
        # adds the `tier` column if upgrading from an older schema.
        for stmt in (
            "CREATE EXTENSION IF NOT EXISTS timescaledb",
            "SELECT create_hypertable('tick_1m', 'ts', if_not_exists => TRUE, migrate_data => TRUE)",
            "SELECT create_hypertable('option_snapshot', 'ts', if_not_exists => TRUE, migrate_data => TRUE)",
            "ALTER TABLE instruments ADD COLUMN IF NOT EXISTS tier INTEGER DEFAULT 2",
        ):
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass


async def get_session() -> AsyncSession:
    async with SessionLocal() as s:
        yield s
