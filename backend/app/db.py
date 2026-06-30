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


class FyersOrder(Base):
    """Snapshot of Fyers orderBook entries. PK includes snapshot_date so the
    table grows by ~one-row-per-(order, day-seen). Captured at 15:35 IST
    daily before the orderbook rolls over to the next session."""
    __tablename__ = "fyers_orders"
    snapshot_date = Column(DateTime, primary_key=True)        # date of the snapshot
    order_id = Column(String, primary_key=True)
    symbol = Column(String)
    qty = Column(Integer)
    filled_qty = Column(Integer)
    remaining_qty = Column(Integer)
    side = Column(Integer)                                    # 1=BUY -1=SELL
    order_type = Column(Integer)                              # 1=Limit 2=Market 3=SL-M 4=SL-L
    product_type = Column(String)
    status = Column(Integer)                                  # Fyers numeric status
    status_message = Column(String)
    limit_price = Column(Float)
    stop_price = Column(Float)
    avg_price = Column(Float)
    order_ts = Column(DateTime)
    raw = Column(String)                                      # full JSON


class FyersTrade(Base):
    """Snapshot of Fyers tradeBook entries — executed fills."""
    __tablename__ = "fyers_trades"
    snapshot_date = Column(DateTime, primary_key=True)
    order_id = Column(String, primary_key=True)
    trade_number = Column(String, primary_key=True)
    symbol = Column(String)
    qty = Column(Integer)
    side = Column(Integer)
    price = Column(Float)
    product_type = Column(String)
    trade_value = Column(Float)
    exchange_order_no = Column(String)
    trade_ts = Column(DateTime)
    raw = Column(String)


class FyersPosition(Base):
    """Daily snapshot of net positions at 15:35 IST."""
    __tablename__ = "fyers_positions"
    snapshot_date = Column(DateTime, primary_key=True)
    symbol = Column(String, primary_key=True)
    product_type = Column(String, primary_key=True)
    net_qty = Column(Integer)
    buy_qty = Column(Integer)
    sell_qty = Column(Integer)
    buy_avg = Column(Float)
    sell_avg = Column(Float)
    realized_pnl = Column(Float)
    unrealized_pnl = Column(Float)
    ltp = Column(Float)
    raw = Column(String)


class OptionContract1m(Base):
    """Per-contract 1-min OHLCV+OI history. Mirrors `tick_1m` but for option
    legs. Populated by the Fyers history endpoint (~100 days back at 1-min
    resolution per contract). Powers truly real RL/strategy backtests —
    replaces the BS-pricing fallback for any (date, strike) we have."""
    __tablename__ = "option_contract_1m"
    ts = Column(DateTime, primary_key=True)
    symbol = Column(String, primary_key=True)        # e.g. NSE:NIFTY2660923000CE
    underlying = Column(String, nullable=False)
    strike = Column(Float, nullable=False)
    expiry = Column(DateTime, nullable=False)
    option_type = Column(String, nullable=False)     # CE | PE
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger, default=0)
    oi = Column(BigInteger, default=0)

    __table_args__ = (
        Index("ix_opt_contract_under_ts", "underlying", "ts"),
        Index("ix_opt_contract_under_exp_strike", "underlying", "expiry", "strike", "option_type", "ts"),
    )


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
    # Tiers: free | paid | algo
    # free  = 15-day trial, 10 strategy saves, 50 backtest runs, no paper/live
    # paid  = $20/mo, unlimited saves + backtests, paper trading enabled
    # algo  = paid + live trading via Fyers
    tier = Column(String, default="free")
    is_active = Column(Boolean, default=True)
    telegram_chat_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Free trial tracking
    trial_expires_at = Column(DateTime, nullable=True)     # 15 days from created_at
    strategy_count = Column(Integer, default=0)            # saved strategies (free: max 10)
    backtest_count = Column(Integer, default=0)            # lifetime runs (free: max 50)

    # Subscription / billing fields
    subscription_id = Column(String, nullable=True, index=True)
    subscription_status = Column(String, nullable=True)    # active | cancelled | expired | paused
    subscription_ends_at = Column(DateTime, nullable=True)
    razorpay_customer_id = Column(String, nullable=True)
    pending_plan = Column(String, nullable=True)

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


# ── Strategy framework (Sprint 0) ───────────────────────────────────
class Strategy(Base):
    """One row per (strategy, version). Copy-on-edit: PATCH creates a
    new row with version+1; older runs still reference their version via
    `strategy_runs.strategy_version` + the immutable `config_snapshot`."""
    __tablename__ = "strategies"
    id = Column(String, primary_key=True)             # uuid (same across versions)
    version = Column(Integer, primary_key=True, default=1)
    owner_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String)
    kind = Column(String, default="CONDITIONAL")      # CONDITIONAL | RL_BANDIT
    status = Column(String, default="DRAFT", index=True)   # DRAFT|BACKTESTED|PAPER_LIVE|LIVE|ARCHIVED
    tier_required = Column(String, default="free")
    created_by = Column(String, default="manual")     # manual|chatbot|template
    chatbot_session_id = Column(String, nullable=True)
    spec = Column(String, nullable=False, default="{}")    # validated StrategySpec JSON
    tags = Column(String, default="[]")               # JSON list
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StrategyRun(Base):
    """One execution of a strategy version — backtest, paper, or live."""
    __tablename__ = "strategy_runs"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    strategy_id = Column(String, nullable=False, index=True)
    strategy_version = Column(Integer, nullable=False)
    owner_id = Column(String, nullable=False, index=True)
    mode = Column(String, nullable=False, index=True)     # BACKTEST|PAPER|LIVE
    status = Column(String, default="RUNNING", index=True)  # RUNNING|COMPLETED|HALTED|ERRORED
    config_snapshot = Column(String, default="{}")        # immutable strategy JSON
    params = Column(String, default="{}")                 # period, capital, seed, friction
    metrics = Column(String, default="{}")                # default metric block
    custom_metrics = Column(String, default="{}")         # user-defined add-ons
    equity_curve = Column(String, default="[]")           # [{ts, equity}, …]
    data_quality = Column(String, default="{}")          # source mix, gaps
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    error_message = Column(String, nullable=True)


class StrategyTrade(Base):
    """One fill inside a run. Audit-grade: entry features captured.
    Separate from `rl_trade` (which is the bandit's research log) so
    user-owned trades have clean lineage."""
    __tablename__ = "strategy_trades"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String, nullable=False, index=True)
    strategy_id = Column(String, nullable=False, index=True)
    strategy_version = Column(Integer, nullable=False)
    entry_ts = Column(DateTime, nullable=False, index=True)
    exit_ts = Column(DateTime, nullable=True)
    entry_signal = Column(String, default="{}")           # feature snapshot at entry
    exit_reason = Column(String, nullable=True)           # TP|SL|TIMEOUT|MANUAL|RISK_GATE
    legs = Column(String, default="[]")                   # [{symbol, action, qty, entry_price, exit_price, fees_inr}]
    gross_pnl_inr = Column(Float, nullable=True)
    net_pnl_inr = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    mae_pct = Column(Float, nullable=True)                # max adverse excursion
    mfe_pct = Column(Float, nullable=True)                # max favorable excursion
    policy_version = Column(String, nullable=True)        # for RL_BANDIT strategies — links to rl_policy snapshot


class OptionEod(Base):
    """End-of-day per-strike F&O data from NSE Bhavcopy. Multi-year
    historical depth (NSE archives go back to ~2010). Powers swing /
    overnight backtests where 1-min granularity isn't needed."""
    __tablename__ = "option_eod"
    trade_date = Column(DateTime, primary_key=True)
    underlying = Column(String, primary_key=True)
    expiry = Column(DateTime, primary_key=True)
    strike = Column(Float, primary_key=True)
    option_type = Column(String, primary_key=True)        # CE | PE | XX(future)
    open = Column(Float); high = Column(Float)
    low = Column(Float); close = Column(Float)
    settle = Column(Float)
    volume = Column(BigInteger, default=0)
    oi = Column(BigInteger, default=0)
    oi_change = Column(BigInteger, default=0)


class OptionIntraday(Base):
    """Per-strike intraday options OHLCV+OI, 1-min granularity.
    Sources: TradingTuitions (NIFTY/BANKNIFTY), Breeze API (all F&O),
    Google Drive bulk imports. Tagged with `source` column for provenance."""
    __tablename__ = "option_intraday"
    ts = Column(DateTime, primary_key=True)
    underlying = Column(String, primary_key=True)
    expiry = Column(DateTime, primary_key=True)
    strike = Column(Float, primary_key=True)
    option_type = Column(String, primary_key=True)        # CE | PE
    open = Column(Float); high = Column(Float)
    low = Column(Float); close = Column(Float)
    volume = Column(BigInteger, default=0)
    oi = Column(BigInteger, default=0)
    oi_change = Column(BigInteger, default=0)
    source = Column(String, default="unknown")

    __table_args__ = (Index("ix_option_intraday_under_ts", "underlying", "ts"),)


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
        # Tier gate / trial columns (added in T4 migration)
        for col_stmt in (
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS tier VARCHAR DEFAULT 'free'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_expires_at TIMESTAMP",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS strategy_count INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS backtest_count INTEGER DEFAULT 0",
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
        # ── Strategy framework tables (Sprint 0) ────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS strategies (
                id VARCHAR NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                owner_id VARCHAR NOT NULL,
                name VARCHAR NOT NULL,
                description VARCHAR,
                kind VARCHAR DEFAULT 'CONDITIONAL',
                status VARCHAR DEFAULT 'DRAFT',
                tier_required VARCHAR DEFAULT 'free',
                created_by VARCHAR DEFAULT 'manual',
                chatbot_session_id VARCHAR,
                spec TEXT NOT NULL DEFAULT '{}',
                tags TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (id, version)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS strategy_runs (
                id VARCHAR PRIMARY KEY,
                strategy_id VARCHAR NOT NULL,
                strategy_version INTEGER NOT NULL,
                owner_id VARCHAR NOT NULL,
                mode VARCHAR NOT NULL,
                status VARCHAR DEFAULT 'RUNNING',
                config_snapshot TEXT DEFAULT '{}',
                params TEXT DEFAULT '{}',
                metrics TEXT DEFAULT '{}',
                custom_metrics TEXT DEFAULT '{}',
                equity_curve TEXT DEFAULT '[]',
                data_quality TEXT DEFAULT '{}',
                started_at TIMESTAMP DEFAULT NOW(),
                ended_at TIMESTAMP,
                error_message TEXT
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS strategy_trades (
                id VARCHAR PRIMARY KEY,
                run_id VARCHAR NOT NULL,
                strategy_id VARCHAR NOT NULL,
                strategy_version INTEGER NOT NULL,
                entry_ts TIMESTAMP NOT NULL,
                exit_ts TIMESTAMP,
                entry_signal TEXT DEFAULT '{}',
                exit_reason VARCHAR,
                legs TEXT DEFAULT '[]',
                gross_pnl_inr FLOAT,
                net_pnl_inr FLOAT,
                pnl_pct FLOAT,
                mae_pct FLOAT,
                mfe_pct FLOAT,
                policy_version VARCHAR
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fyers_orders (
                snapshot_date TIMESTAMP NOT NULL,
                order_id VARCHAR NOT NULL,
                symbol VARCHAR,
                qty INTEGER, filled_qty INTEGER, remaining_qty INTEGER,
                side INTEGER, order_type INTEGER,
                product_type VARCHAR,
                status INTEGER, status_message VARCHAR,
                limit_price FLOAT, stop_price FLOAT, avg_price FLOAT,
                order_ts TIMESTAMP,
                raw TEXT,
                PRIMARY KEY (snapshot_date, order_id)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fyers_trades (
                snapshot_date TIMESTAMP NOT NULL,
                order_id VARCHAR NOT NULL,
                trade_number VARCHAR NOT NULL,
                symbol VARCHAR,
                qty INTEGER, side INTEGER,
                price FLOAT, product_type VARCHAR,
                trade_value FLOAT,
                exchange_order_no VARCHAR,
                trade_ts TIMESTAMP,
                raw TEXT,
                PRIMARY KEY (snapshot_date, order_id, trade_number)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fyers_positions (
                snapshot_date TIMESTAMP NOT NULL,
                symbol VARCHAR NOT NULL,
                product_type VARCHAR NOT NULL,
                net_qty INTEGER, buy_qty INTEGER, sell_qty INTEGER,
                buy_avg FLOAT, sell_avg FLOAT,
                realized_pnl FLOAT, unrealized_pnl FLOAT,
                ltp FLOAT,
                raw TEXT,
                PRIMARY KEY (snapshot_date, symbol, product_type)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS option_contract_1m (
                ts TIMESTAMP NOT NULL,
                symbol VARCHAR NOT NULL,
                underlying VARCHAR NOT NULL,
                strike FLOAT NOT NULL,
                expiry TIMESTAMP NOT NULL,
                option_type VARCHAR NOT NULL,
                open FLOAT, high FLOAT, low FLOAT, close FLOAT,
                volume BIGINT DEFAULT 0,
                oi BIGINT DEFAULT 0,
                PRIMARY KEY (ts, symbol)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS option_eod (
                trade_date TIMESTAMP NOT NULL,
                underlying VARCHAR NOT NULL,
                expiry TIMESTAMP NOT NULL,
                strike FLOAT NOT NULL,
                option_type VARCHAR NOT NULL,
                open FLOAT, high FLOAT, low FLOAT, close FLOAT,
                settle FLOAT,
                volume BIGINT DEFAULT 0,
                oi BIGINT DEFAULT 0,
                oi_change BIGINT DEFAULT 0,
                PRIMARY KEY (trade_date, underlying, expiry, strike, option_type)
            )
        """))
        for stmt in (
            "CREATE EXTENSION IF NOT EXISTS timescaledb",
            "SELECT create_hypertable('tick_1m', 'ts', if_not_exists => TRUE, migrate_data => TRUE)",
            "SELECT create_hypertable('option_snapshot', 'ts', if_not_exists => TRUE, migrate_data => TRUE)",
            "SELECT create_hypertable('option_strike_snapshot', 'ts', if_not_exists => TRUE, migrate_data => TRUE)",
            "SELECT create_hypertable('option_eod', 'trade_date', if_not_exists => TRUE, migrate_data => TRUE, chunk_time_interval => INTERVAL '90 days')",
            "SELECT create_hypertable('option_contract_1m', 'ts', if_not_exists => TRUE, migrate_data => TRUE, chunk_time_interval => INTERVAL '7 days')",
            "CREATE INDEX IF NOT EXISTS ix_opt_contract_under_ts ON option_contract_1m (underlying, ts)",
            "CREATE INDEX IF NOT EXISTS ix_opt_contract_lookup ON option_contract_1m (underlying, expiry, strike, option_type, ts)",
            # Timescale compression — chunks older than 14 days compress to
            # ~10% of original size. Keeps the dataset growing for years
            # without disk blowup. Idempotent — `do $$ ... $$` blocks check
            # before adding the policy.
            """
            DO $$
            BEGIN
                BEGIN
                    ALTER TABLE option_contract_1m SET (
                        timescaledb.compress,
                        timescaledb.compress_segmentby = 'symbol,underlying',
                        timescaledb.compress_orderby = 'ts DESC'
                    );
                EXCEPTION WHEN OTHERS THEN NULL;
                END;
                BEGIN
                    PERFORM add_compression_policy('option_contract_1m', INTERVAL '14 days');
                EXCEPTION WHEN duplicate_object THEN NULL;
                END;
                BEGIN
                    ALTER TABLE option_strike_snapshot SET (
                        timescaledb.compress,
                        timescaledb.compress_segmentby = 'underlying',
                        timescaledb.compress_orderby = 'ts DESC'
                    );
                EXCEPTION WHEN OTHERS THEN NULL;
                END;
                BEGIN
                    PERFORM add_compression_policy('option_strike_snapshot', INTERVAL '14 days');
                EXCEPTION WHEN duplicate_object THEN NULL;
                END;
                BEGIN
                    ALTER TABLE tick_1m SET (
                        timescaledb.compress,
                        timescaledb.compress_segmentby = 'symbol',
                        timescaledb.compress_orderby = 'ts DESC'
                    );
                EXCEPTION WHEN OTHERS THEN NULL;
                END;
                BEGIN
                    PERFORM add_compression_policy('tick_1m', INTERVAL '14 days');
                EXCEPTION WHEN duplicate_object THEN NULL;
                END;
            END $$;
            """,
            "CREATE INDEX IF NOT EXISTS ix_api_keys_user ON api_keys (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_api_keys_hash ON api_keys (key_hash)",
            "CREATE INDEX IF NOT EXISTS ix_rl_trade_under_ts ON rl_trade (underlying, entry_ts DESC)",
            "CREATE INDEX IF NOT EXISTS ix_rl_trade_status ON rl_trade (status)",
            "CREATE INDEX IF NOT EXISTS ix_strategies_owner ON strategies (owner_id, status)",
            "CREATE INDEX IF NOT EXISTS ix_strategy_runs_strategy ON strategy_runs (strategy_id, strategy_version)",
            "CREATE INDEX IF NOT EXISTS ix_strategy_runs_owner_mode ON strategy_runs (owner_id, mode, status)",
            "CREATE INDEX IF NOT EXISTS ix_strategy_trades_run ON strategy_trades (run_id, entry_ts)",
            "CREATE INDEX IF NOT EXISTS ix_strategy_trades_strategy ON strategy_trades (strategy_id, strategy_version)",
            "CREATE INDEX IF NOT EXISTS ix_option_eod_under_exp ON option_eod (underlying, expiry, trade_date)",
            """
            CREATE TABLE IF NOT EXISTS option_intraday (
                ts TIMESTAMP NOT NULL,
                underlying VARCHAR NOT NULL,
                expiry TIMESTAMP NOT NULL,
                strike FLOAT NOT NULL,
                option_type VARCHAR NOT NULL,
                open FLOAT, high FLOAT, low FLOAT, close FLOAT,
                volume BIGINT DEFAULT 0,
                oi BIGINT DEFAULT 0,
                oi_change BIGINT DEFAULT 0,
                source VARCHAR DEFAULT 'unknown',
                PRIMARY KEY (ts, underlying, expiry, strike, option_type)
            )
            """,
        ):
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass
        # Hypertable for option_intraday (separate loop to handle if_not_exists)
        for stmt in (
            "SELECT create_hypertable('option_intraday', 'ts', if_not_exists => TRUE, migrate_data => TRUE, chunk_time_interval => INTERVAL '7 days')",
            "CREATE INDEX IF NOT EXISTS ix_option_intraday_under_ts ON option_intraday (underlying, ts)",
        ):
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass


async def get_session() -> AsyncSession:
    async with SessionLocal() as s:
        yield s
