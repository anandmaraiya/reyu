"""SQLAlchemy async DB with TimescaleDB hypertables.

Two time-series tables:
  - tick_1m: 1-min OHLCV per instrument
  - option_snapshot: aggregate option-chain metrics (PCR / OI / IV) per
    underlying+expiry, sampled every SNAPSHOT_INTERVAL_SEC

Relational tables:
  - users: platform user accounts with tier + API key management
"""
from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, BigInteger, DateTime, Integer, Index, text, Boolean,
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


class OptionStrikeSnapshot(Base):
    """Per-strike option-chain snapshot. Captures ATM ± 10 strikes per poll
    so the RL feature extractor can use real OI / IV / premium history
    rather than aggregate-only values from `option_snapshot`.

    Volume guard: ~21 rows × 60s × 200 symbols ≈ 250k rows/day. Hypertable
    chunking + 30-day retention keeps disk usage modest.
    """
    __tablename__ = "option_strike_snapshot"
    ts = Column(DateTime, primary_key=True)
    underlying = Column(String, primary_key=True)
    strike = Column(Float, primary_key=True)
    expiry = Column(DateTime, primary_key=True)
    ce_oi = Column(BigInteger, default=0)
    ce_oi_change = Column(BigInteger, default=0)
    ce_volume = Column(BigInteger, default=0)
    ce_ltp = Column(Float)
    ce_iv = Column(Float)
    pe_oi = Column(BigInteger, default=0)
    pe_oi_change = Column(BigInteger, default=0)
    pe_volume = Column(BigInteger, default=0)
    pe_ltp = Column(Float)
    pe_iv = Column(Float)
    spot = Column(Float)

    __table_args__ = (Index("ix_strike_snap_under_ts", "underlying", "ts"),)


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


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    tier = Column(String, default="free")             # free | pro | algo
    is_active = Column(Boolean, default=True)
    telegram_chat_id = Column(String, nullable=True, index=True)  # set when user links Telegram
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Subscription / billing fields
    subscription_id = Column(String, nullable=True, index=True)   # Razorpay subscription_id
    subscription_status = Column(String, nullable=True)           # active | cancelled | expired | paused
    subscription_ends_at = Column(DateTime, nullable=True)        # when current paid period ends
    razorpay_customer_id = Column(String, nullable=True)          # Razorpay customer_id
    pending_plan = Column(String, nullable=True)                  # plan to switch to at period end

    __table_args__ = (Index("ix_users_email", "email"),)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    key_hash = Column(String, unique=True, nullable=False)
    name = Column(String, default="default")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)


# ── Reinforcement learning ──────────────────────────────────────
class RLPolicy(Base):
    """Per-underlying contextual-bandit policy. `weights` is JSON-encoded.
    `target_pct` / `stop_pct` are the bracket sizes used at entry; the
    reward function scales with their ratio so any 1:1 / 2:1 / asymmetric
    setting works without code changes."""
    __tablename__ = "rl_policy"
    underlying = Column(String, primary_key=True)     # e.g. "NSE:NIFTY50-INDEX"
    weights = Column(String, nullable=False, default="{}")     # JSON blob
    n_trades = Column(Integer, default=0)
    n_wins = Column(Integer, default=0)
    cum_reward = Column(Float, default=0.0)
    last_trained_at = Column(DateTime, nullable=True)
    epsilon = Column(Float, default=0.10)
    enabled = Column(Boolean, default=True)
    target_pct = Column(Float, default=0.20)          # TP at +20% on premium
    stop_pct = Column(Float, default=0.20)            # SL at -20% on premium (1:1)
    min_conviction = Column(Float, default=0.0)       # greedy-mode FLAT filter; tuned per symbol
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RLTrade(Base):
    """One paper-trade run. `features` is JSON-encoded snapshot at entry.
    `status` ∈ OPEN | TP | SL | TIMEOUT. Reward computed on close."""
    __tablename__ = "rl_trade"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    underlying = Column(String, nullable=False, index=True)
    leg_symbol = Column(String, nullable=False)
    action = Column(String, nullable=False)               # LONG | SHORT
    strike = Column(Float)
    option_type = Column(String)                          # CE | PE
    qty = Column(Integer, default=1)
    entry_ts = Column(DateTime, default=datetime.utcnow, index=True)
    entry_premium = Column(Float, nullable=False)
    target_premium = Column(Float, nullable=False)
    stop_premium = Column(Float, nullable=False)
    exit_ts = Column(DateTime, nullable=True)
    exit_premium = Column(Float, nullable=True)
    status = Column(String, default="OPEN", index=True)   # OPEN | TP | SL | TIMEOUT
    reward = Column(Float, nullable=True)                 # +1 TP, -0.5 SL, 0 timeout
    pnl_pct = Column(Float, nullable=True)
    features = Column(String, default="{}")               # JSON state vector
    paper = Column(Boolean, default=True)                 # False ⇒ real Fyers order
    action_logprob = Column(Float, nullable=True)         # for policy gradient


async def init_db() -> None:
    """Create tables + promote time-series tables to Timescale hypertables."""
    async with engine.begin() as conn:
        # Use raw SQL with IF NOT EXISTS for true idempotency across
        # uvicorn reloads that may interrupt Python-level create_all.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS instruments (
                symbol VARCHAR PRIMARY KEY,
                name VARCHAR,
                exch VARCHAR,
                segment VARCHAR,
                lot_size INTEGER DEFAULT 1,
                tick_size FLOAT DEFAULT 0.05,
                expiry TIMESTAMP,
                strike FLOAT,
                option_type VARCHAR,
                underlying VARCHAR,
                tracked INTEGER DEFAULT 0,
                tier INTEGER DEFAULT 2
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tick_1m (
                ts TIMESTAMP NOT NULL,
                symbol VARCHAR NOT NULL,
                open FLOAT, high FLOAT, low FLOAT, close FLOAT,
                volume BIGINT DEFAULT 0, oi BIGINT DEFAULT 0,
                PRIMARY KEY (ts, symbol)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS option_strike_snapshot (
                ts TIMESTAMP NOT NULL,
                underlying VARCHAR NOT NULL,
                strike FLOAT NOT NULL,
                expiry TIMESTAMP NOT NULL,
                ce_oi BIGINT DEFAULT 0, ce_oi_change BIGINT DEFAULT 0,
                ce_volume BIGINT DEFAULT 0, ce_ltp FLOAT, ce_iv FLOAT,
                pe_oi BIGINT DEFAULT 0, pe_oi_change BIGINT DEFAULT 0,
                pe_volume BIGINT DEFAULT 0, pe_ltp FLOAT, pe_iv FLOAT,
                spot FLOAT,
                PRIMARY KEY (ts, underlying, strike, expiry)
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_strike_snap_under_ts ON option_strike_snapshot (underlying, ts)"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS option_snapshot (
                ts TIMESTAMP NOT NULL,
                symbol VARCHAR NOT NULL,
                expiry TIMESTAMP NOT NULL,
                ltp FLOAT, pcr_oi FLOAT, pcr_volume FLOAT,
                max_pain FLOAT, atm_strike FLOAT, atm_iv FLOAT,
                total_ce_oi BIGINT DEFAULT 0, total_pe_oi BIGINT DEFAULT 0,
                ce_oi_change BIGINT DEFAULT 0, pe_oi_change BIGINT DEFAULT 0,
                bias_score INTEGER DEFAULT 0,
                PRIMARY KEY (ts, symbol, expiry)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR PRIMARY KEY,
                email VARCHAR UNIQUE NOT NULL,
                password_hash VARCHAR NOT NULL,
                display_name VARCHAR,
                tier VARCHAR DEFAULT 'free',
                is_active BOOLEAN DEFAULT TRUE,
                telegram_chat_id VARCHAR,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_chat_id VARCHAR"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_users_telegram ON users (telegram_chat_id)"
        ))
        # Subscription / billing columns
        for col_stmt in (
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_id VARCHAR",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status VARCHAR",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_ends_at TIMESTAMP",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS razorpay_customer_id VARCHAR",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS pending_plan VARCHAR",
            "CREATE INDEX IF NOT EXISTS ix_users_subscription ON users (subscription_id)",
        ):
            try:
                await conn.execute(text(col_stmt))
            except Exception:
                pass
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                key_hash VARCHAR UNIQUE NOT NULL,
                name VARCHAR DEFAULT 'default',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW(),
                last_used_at TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rl_policy (
                underlying VARCHAR PRIMARY KEY,
                weights TEXT NOT NULL DEFAULT '{}',
                n_trades INTEGER DEFAULT 0,
                n_wins INTEGER DEFAULT 0,
                cum_reward FLOAT DEFAULT 0.0,
                last_trained_at TIMESTAMP,
                epsilon FLOAT DEFAULT 0.10,
                enabled BOOLEAN DEFAULT TRUE,
                target_pct FLOAT DEFAULT 0.20,
                stop_pct FLOAT DEFAULT 0.20,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "ALTER TABLE rl_policy ADD COLUMN IF NOT EXISTS target_pct FLOAT DEFAULT 0.20"
        ))
        await conn.execute(text(
            "ALTER TABLE rl_policy ADD COLUMN IF NOT EXISTS stop_pct FLOAT DEFAULT 0.20"
        ))
        await conn.execute(text(
            "ALTER TABLE rl_policy ADD COLUMN IF NOT EXISTS min_conviction FLOAT DEFAULT 0.0"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rl_trade (
                id VARCHAR PRIMARY KEY,
                underlying VARCHAR NOT NULL,
                leg_symbol VARCHAR NOT NULL,
                action VARCHAR NOT NULL,
                strike FLOAT,
                option_type VARCHAR,
                qty INTEGER DEFAULT 1,
                entry_ts TIMESTAMP DEFAULT NOW(),
                entry_premium FLOAT NOT NULL,
                target_premium FLOAT NOT NULL,
                stop_premium FLOAT NOT NULL,
                exit_ts TIMESTAMP,
                exit_premium FLOAT,
                status VARCHAR DEFAULT 'OPEN',
                reward FLOAT,
                pnl_pct FLOAT,
                features TEXT DEFAULT '{}',
                paper BOOLEAN DEFAULT TRUE,
                action_logprob FLOAT
            )
        """))
        for stmt in (
            "CREATE EXTENSION IF NOT EXISTS timescaledb",
            "SELECT create_hypertable('tick_1m', 'ts', if_not_exists => TRUE, migrate_data => TRUE)",
            "SELECT create_hypertable('option_snapshot', 'ts', if_not_exists => TRUE, migrate_data => TRUE)",
            "SELECT create_hypertable('option_strike_snapshot', 'ts', if_not_exists => TRUE, migrate_data => TRUE)",
            "CREATE INDEX IF NOT EXISTS ix_api_keys_user ON api_keys (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_api_keys_hash ON api_keys (key_hash)",
            "CREATE INDEX IF NOT EXISTS ix_rl_trade_under_ts ON rl_trade (underlying, entry_ts DESC)",
            "CREATE INDEX IF NOT EXISTS ix_rl_trade_status ON rl_trade (status)",
        ):
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass


async def get_session() -> AsyncSession:
    async with SessionLocal() as s:
        yield s
