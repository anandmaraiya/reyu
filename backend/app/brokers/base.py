"""Abstract broker client interface.

Every broker adapter must implement this interface. The rest of the system
(scheduler, agent tools, order router) talks ONLY to this interface —
never to a broker-specific SDK directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ─── Domain types ────────────────────────────────────────────────────────────

@dataclass
class Quote:
    symbol: str
    ltp: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    oi: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class OptionLeg:
    symbol: str          # broker-native symbol, e.g. NSE:NIFTY2462624800CE
    strike: float
    expiry: datetime
    option_type: str     # CE | PE
    oi: int = 0
    oi_change: int = 0
    volume: int = 0
    ltp: float = 0.0
    iv: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0


@dataclass
class OptionChain:
    underlying: str
    spot: float
    expiry: datetime
    atm_strike: float
    legs: list[OptionLeg] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Position:
    symbol: str
    product: str          # INTRADAY | DELIVERY | MARGIN
    qty: int              # net qty (negative = short)
    avg_price: float
    ltp: float
    pnl: float
    pnl_pct: float
    side: str             # LONG | SHORT
    broker_id: str = ""


@dataclass
class Order:
    order_id: str
    symbol: str
    side: str             # BUY | SELL
    qty: int
    filled_qty: int
    order_type: str       # MARKET | LIMIT | SL | SL-M
    price: float
    status: str           # PENDING | OPEN | COMPLETE | CANCELLED | REJECTED
    placed_at: datetime = field(default_factory=datetime.utcnow)
    message: str = ""


@dataclass
class OrderRequest:
    symbol: str
    side: str             # BUY | SELL
    qty: int
    order_type: str = "MARKET"
    price: float = 0.0
    stop_price: float = 0.0
    product: str = "INTRADAY"
    dry_run: bool = True  # Always default dry-run — explicitly opt in to live


@dataclass
class AccountProfile:
    user_id: str
    name: str
    email: str
    broker: str
    funds_available: float = 0.0
    funds_used: float = 0.0


@dataclass
class HistoryBar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    oi: int = 0


# ─── Abstract interface ───────────────────────────────────────────────────────

class BrokerClient(ABC):
    """Abstract interface all broker adapters must implement."""

    broker_id: str = "unknown"       # e.g. "fyers", "zerodha", "angelone"
    broker_name: str = "Unknown"     # Display name, e.g. "Fyers"

    # ── Auth ──────────────────────────────────────────────────────────────────

    @abstractmethod
    def oauth_url(self, redirect_uri: str, state: str = "") -> str:
        """Return the broker login URL to redirect the user to."""

    @abstractmethod
    async def exchange_token(self, code: str, redirect_uri: str) -> dict:
        """Exchange an auth code for access tokens. Returns a dict with
        at least: access_token, refresh_token (if any), expires_at (ISO str)."""

    @abstractmethod
    async def refresh_token(self, refresh_token: str) -> dict:
        """Refresh an expired access token. Returns same shape as exchange_token."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True if the client holds a valid, non-expired access token."""

    # ── Market data ───────────────────────────────────────────────────────────

    @abstractmethod
    async def get_quotes(self, symbols: list[str]) -> list[Quote]:
        """Fetch live LTPs for a list of symbols."""

    @abstractmethod
    async def get_option_chain(self, underlying: str, expiry: datetime | None = None) -> OptionChain:
        """Fetch the full option chain for an underlying and expiry.
        If expiry is None, return the nearest weekly/monthly expiry."""

    @abstractmethod
    async def get_history(
        self,
        symbol: str,
        resolution: str,          # "1", "5", "15", "D"
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[HistoryBar]:
        """Fetch OHLCV history bars."""

    # ── Account ───────────────────────────────────────────────────────────────

    @abstractmethod
    async def get_profile(self) -> AccountProfile:
        """Fetch user profile and fund balances."""

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Fetch open positions."""

    @abstractmethod
    async def get_orders(self) -> list[Order]:
        """Fetch today's orders."""

    # ── Trading ───────────────────────────────────────────────────────────────

    @abstractmethod
    async def place_order(self, req: OrderRequest) -> Order:
        """Place or simulate an order. Must respect req.dry_run."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True on success."""

    @abstractmethod
    async def get_margin(self, orders: list[OrderRequest]) -> dict:
        """Calculate margin required for a basket of orders."""

    # ── Instruments ───────────────────────────────────────────────────────────

    @abstractmethod
    async def search_symbols(self, query: str) -> list[dict]:
        """Search for instrument symbols by name or ticker."""

    def symbol_for_option(
        self,
        underlying: str,
        expiry: datetime,
        strike: float,
        option_type: str,   # CE | PE
    ) -> str:
        """Construct a broker-native option symbol. Override per broker."""
        raise NotImplementedError
