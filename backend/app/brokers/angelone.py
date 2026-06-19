"""AngelOne Smart API broker adapter (stub).

Install: pip install smartapi-python
Docs: https://smartapi.angelbroking.com/docs
"""
from __future__ import annotations

from datetime import datetime
from app.brokers.base import (
    BrokerClient, Quote, OptionChain, Position,
    Order, OrderRequest, AccountProfile, HistoryBar,
)


class AngelOneBroker(BrokerClient):
    broker_id   = "angelone"
    broker_name = "AngelOne"

    API_KEY = ""    # Set via env ANGELONE_API_KEY

    def __init__(self, access_token: str | None = None):
        self._token = access_token
        self._smart = None
        if access_token:
            self._init_sdk(access_token)

    def _init_sdk(self, token: str):
        try:
            from SmartApi import SmartConnect
            self._smart = SmartConnect(api_key=self.API_KEY)
            self._smart.setAccessToken(token)
        except ImportError:
            pass

    def oauth_url(self, redirect_uri: str, state: str = "") -> str:
        # AngelOne uses TOTP-based login, not OAuth redirect
        return f"https://smartapi.angelbroking.com/publisher-login?api_key={self.API_KEY}"

    async def exchange_token(self, code: str, redirect_uri: str) -> dict:
        # AngelOne exchanges TOTP code for session
        raise NotImplementedError("AngelOne TOTP exchange — TODO")

    async def refresh_token(self, refresh_token: str) -> dict:
        raise NotImplementedError("AngelOne refresh — TODO")

    @property
    def is_connected(self) -> bool:
        return self._smart is not None and self._token is not None

    async def get_quotes(self, symbols: list[str]) -> list[Quote]:
        if not self._smart:
            return []
        # AngelOne uses token-based symbol lookup
        # TODO: convert NSE:SYMBOL format to AngelOne exchange:token format
        return []

    async def get_option_chain(self, underlying: str, expiry: datetime | None = None) -> OptionChain:
        raise NotImplementedError("AngelOne option chain — TODO")

    async def get_history(self, symbol: str, resolution: str, from_dt: datetime, to_dt: datetime) -> list[HistoryBar]:
        return []

    async def get_profile(self) -> AccountProfile:
        if not self._smart:
            return AccountProfile("", "", "", "angelone")
        profile = self._smart.getProfile(None)
        return AccountProfile(
            user_id=profile.get("data", {}).get("clientcode", ""),
            name=profile.get("data", {}).get("name", ""),
            email=profile.get("data", {}).get("email", ""),
            broker="angelone",
        )

    async def get_positions(self) -> list[Position]:
        return []

    async def get_orders(self) -> list[Order]:
        return []

    async def place_order(self, req: OrderRequest) -> Order:
        return Order(
            order_id=f"DRY-{int(datetime.utcnow().timestamp())}",
            symbol=req.symbol, side=req.side, qty=req.qty, filled_qty=0,
            order_type=req.order_type, price=req.price, status="DRY_RUN",
        )

    async def cancel_order(self, order_id: str) -> bool:
        return False

    async def get_margin(self, orders: list[OrderRequest]) -> dict:
        return {"total": 0.0, "available": 0.0, "required": 0.0}

    async def search_symbols(self, query: str) -> list[dict]:
        return []
