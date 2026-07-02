"""Zerodha Kite Connect broker adapter (stub).

Install: pip install kiteconnect
Docs: https://kite.trade/docs/connect/v3/
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi.concurrency import run_in_threadpool

from app.brokers.base import (
    BrokerClient, Quote, OptionChain, OptionLeg, Position,
    Order, OrderRequest, AccountProfile, HistoryBar,
)
from app.config import settings

log = logging.getLogger("reyu.zerodha")


class ZerodhaBroker(BrokerClient):
    broker_id   = "zerodha"
    broker_name = "Zerodha"

    def __init__(self, access_token: str | None = None):
        self.api_key = settings.zerodha_api_key
        self.api_secret = settings.zerodha_api_secret
        self._token = access_token
        self._kite = None
        if access_token:
            self._init_sdk(access_token)

    def _init_sdk(self, token: str):
        try:
            from kiteconnect import KiteConnect
            self._kite = KiteConnect(api_key=self.api_key)
            self._kite.set_access_token(token)
        except ImportError:
            log.warning("kiteconnect not installed — pip install kiteconnect")
        except Exception as e:
            log.warning("KiteConnect init failed: %s", e)

    def oauth_url(self, redirect_uri: str, state: str = "") -> str:
        # Kite ignores redirect_uri here — it's configured in the dashboard.
        # State is optional; we bundle it as a query param Kite carries through.
        base = f"https://kite.zerodha.com/connect/login?v=3&api_key={self.api_key}"
        return f"{base}&redirect_params=state%3D{state}" if state else base

    async def exchange_token(self, code: str, redirect_uri: str) -> dict:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("ZERODHA_API_KEY + ZERODHA_API_SECRET required")
        try:
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=self.api_key)
        except ImportError:
            raise RuntimeError("kiteconnect not installed on server")
        data = await run_in_threadpool(kite.generate_session, code, api_secret=self.api_secret)
        token = data.get("access_token", "")
        if token:
            self._token = token
            self._init_sdk(token)
        return {
            "access_token": token,
            "refresh_token": data.get("refresh_token"),
            "expires_at": "next 06:00 IST",
        }

    async def refresh_token(self, refresh_token: str) -> dict:
        raise NotImplementedError("Zerodha tokens expire daily — re-auth required")

    @property
    def is_connected(self) -> bool:
        return self._kite is not None and self._token is not None

    async def get_quotes(self, symbols: list[str]) -> list[Quote]:
        if not self._kite:
            return []
        try:
            data = await run_in_threadpool(self._kite.quote, symbols)
        except Exception as e:
            log.warning("kite.quote failed: %s", e)
            return []
        return [
            Quote(
                symbol=sym,
                ltp=v.get("last_price", 0.0),
                open=v.get("ohlc", {}).get("open", 0.0),
                high=v.get("ohlc", {}).get("high", 0.0),
                low=v.get("ohlc", {}).get("low", 0.0),
                close=v.get("ohlc", {}).get("close", 0.0),
                volume=v.get("volume", 0),
                oi=v.get("oi", 0),
            )
            for sym, v in data.items()
        ]

    async def get_option_chain(self, underlying: str, expiry: datetime | None = None) -> OptionChain:
        # Zerodha does not have a native option chain endpoint;
        # must be constructed from instruments + quotes.
        raise NotImplementedError("Zerodha option chain requires instruments lookup + quote call — TODO")

    async def get_history(self, symbol: str, resolution: str, from_dt: datetime, to_dt: datetime) -> list[HistoryBar]:
        if not self._kite:
            return []
        interval_map = {"1": "minute", "5": "5minute", "15": "15minute", "D": "day"}
        try:
            data = await run_in_threadpool(
                self._kite.historical_data, symbol, from_dt, to_dt,
                interval_map.get(resolution, "minute"),
            )
        except Exception as e:
            log.warning("kite.historical_data failed: %s", e)
            return []
        return [
            HistoryBar(ts=d["date"], open=d["open"], high=d["high"], low=d["low"],
                       close=d["close"], volume=d.get("volume", 0), oi=d.get("oi", 0))
            for d in data
        ]

    async def get_profile(self) -> AccountProfile:
        if not self._kite:
            return AccountProfile("", "", "", "zerodha")
        p = self._kite.profile()
        margins = self._kite.margins("equity")
        return AccountProfile(
            user_id=p["user_id"], name=p["user_name"], email=p["email"],
            broker="zerodha",
            funds_available=margins.get("available", {}).get("live_balance", 0.0),
            funds_used=margins.get("utilised", {}).get("debits", 0.0),
        )

    async def get_positions(self) -> list[Position]:
        if not self._kite:
            return []
        data = self._kite.positions()
        return [
            Position(
                symbol=p["tradingsymbol"],
                product=p["product"],
                qty=p["quantity"],
                avg_price=p["average_price"],
                ltp=p["last_price"],
                pnl=p["pnl"],
                pnl_pct=(p["pnl"] / (p["average_price"] * abs(p["quantity"])) * 100) if p["average_price"] else 0.0,
                side="LONG" if p["quantity"] > 0 else "SHORT",
                broker_id="zerodha",
            )
            for p in data.get("net", [])
        ]

    async def get_orders(self) -> list[Order]:
        if not self._kite:
            return []
        return [
            Order(
                order_id=o["order_id"],
                symbol=o["tradingsymbol"],
                side=o["transaction_type"],
                qty=o["quantity"],
                filled_qty=o["filled_quantity"],
                order_type=o["order_type"],
                price=o.get("price", 0.0),
                status=o["status"],
                message=o.get("status_message", ""),
            )
            for o in self._kite.orders()
        ]

    async def place_order(self, req: OrderRequest) -> Order:
        if req.dry_run or not self._kite:
            return Order(
                order_id=f"DRY-{int(datetime.utcnow().timestamp())}",
                symbol=req.symbol, side=req.side, qty=req.qty, filled_qty=0,
                order_type=req.order_type, price=req.price, status="DRY_RUN",
                message="Paper trade",
            )
        order_id = self._kite.place_order(
            variety=self._kite.VARIETY_REGULAR,
            exchange=self._kite.EXCHANGE_NFO,
            tradingsymbol=req.symbol,
            transaction_type=req.side,
            quantity=req.qty,
            order_type=req.order_type,
            product=req.product,
            price=req.price if req.order_type == "LIMIT" else None,
        )
        return Order(order_id=order_id, symbol=req.symbol, side=req.side, qty=req.qty,
                     filled_qty=0, order_type=req.order_type, price=req.price, status="OPEN")

    async def cancel_order(self, order_id: str) -> bool:
        if not self._kite:
            return False
        self._kite.cancel_order(variety=self._kite.VARIETY_REGULAR, order_id=order_id)
        return True

    async def get_margin(self, orders: list[OrderRequest]) -> dict:
        return {"total": 0.0, "available": 0.0, "required": 0.0}

    async def search_symbols(self, query: str) -> list[dict]:
        return []
