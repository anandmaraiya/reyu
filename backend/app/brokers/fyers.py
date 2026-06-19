"""Fyers v3 broker adapter.

Wraps the existing app.fyers.client into the BrokerClient interface.
All new code should use this adapter — never call fyers SDK directly.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.brokers.base import (
    BrokerClient, Quote, OptionChain, OptionLeg, Position,
    Order, OrderRequest, AccountProfile, HistoryBar,
)
from app.config import settings


class FyersBroker(BrokerClient):
    broker_id   = "fyers"
    broker_name = "Fyers"

    def __init__(self, access_token: str | None = None):
        self._token = access_token
        self._fy = None
        if access_token:
            self._init_sdk(access_token)

    def _init_sdk(self, token: str):
        try:
            from fyers_apiv3 import fyersModel
            self._fy = fyersModel.FyersModel(
                client_id=settings.fyers_app_id,
                token=token,
                log_path="",
            )
        except Exception:
            self._fy = None

    # ── Auth ──────────────────────────────────────────────────────────────────

    def oauth_url(self, redirect_uri: str, state: str = "") -> str:
        try:
            from fyers_apiv3.fyersModel import SessionModel
            session = SessionModel(
                client_id=settings.fyers_app_id,
                secret_key=settings.fyers_secret_key,
                redirect_uri=redirect_uri,
                response_type="code",
                grant_type="authorization_code",
            )
            return session.generate_authcode()
        except Exception as e:
            raise RuntimeError(f"Fyers oauth_url failed: {e}")

    async def exchange_token(self, code: str, redirect_uri: str) -> dict:
        try:
            from fyers_apiv3.fyersModel import SessionModel
            session = SessionModel(
                client_id=settings.fyers_app_id,
                secret_key=settings.fyers_secret_key,
                redirect_uri=redirect_uri,
                response_type="code",
                grant_type="authorization_code",
            )
            session.set_token(code)
            resp = session.generate_token()
            if resp.get("code") != 200:
                raise RuntimeError(resp.get("message", "Token exchange failed"))
            token = resp["access_token"]
            self._token = token
            self._init_sdk(token)
            return {"access_token": token, "refresh_token": None, "expires_at": None}
        except Exception as e:
            raise RuntimeError(f"Fyers exchange_token failed: {e}")

    async def refresh_token(self, refresh_token: str) -> dict:
        # Fyers v3 tokens expire daily; re-auth required
        raise NotImplementedError("Fyers requires re-authentication via OAuth daily")

    @property
    def is_connected(self) -> bool:
        return self._fy is not None and self._token is not None

    # ── Market data ───────────────────────────────────────────────────────────

    async def get_quotes(self, symbols: list[str]) -> list[Quote]:
        if not self._fy:
            return self._demo_quotes(symbols)
        try:
            resp = self._fy.quotes({"symbols": ",".join(symbols)})
            quotes = []
            for item in (resp.get("d") or []):
                v = item.get("v", {})
                quotes.append(Quote(
                    symbol=item.get("n", ""),
                    ltp=v.get("lp", 0.0),
                    open=v.get("open_price", 0.0),
                    high=v.get("high_price", 0.0),
                    low=v.get("low_price", 0.0),
                    close=v.get("prev_close_price", 0.0),
                    volume=v.get("volume", 0),
                    oi=v.get("oi", 0),
                ))
            return quotes
        except Exception:
            return self._demo_quotes(symbols)

    async def get_option_chain(self, underlying: str, expiry: datetime | None = None) -> OptionChain:
        if not self._fy:
            return self._demo_chain(underlying)
        try:
            params = {"symbol": underlying, "strikecount": 20, "timestamp": ""}
            resp = self._fy.optionchain(params)
            if resp.get("code") != 200:
                return self._demo_chain(underlying)
            data = resp.get("data", {})
            spot = data.get("ltp", 0.0)
            expiry_list = data.get("expiryData", [])
            target_expiry = expiry_list[0] if expiry_list else None

            legs = []
            for row in data.get("optionsChain", []):
                exp_dt = datetime.strptime(target_expiry, "%d-%b-%Y") if target_expiry else datetime.utcnow()
                for opt_type, prefix in [("CE", "CE"), ("PE", "PE")]:
                    key = prefix.lower()
                    legs.append(OptionLeg(
                        symbol=row.get(f"{key}_symbol", ""),
                        strike=row.get("strikePrice", 0),
                        expiry=exp_dt,
                        option_type=opt_type,
                        oi=row.get(f"{key}_oi", 0),
                        oi_change=row.get(f"{key}_oiChange", 0),
                        volume=row.get(f"{key}_volume", 0),
                        ltp=row.get(f"{key}_ltp", 0.0),
                        iv=row.get(f"{key}_iv", 0.0),
                    ))

            atm = min((l.strike for l in legs), key=lambda s: abs(s - spot), default=spot)
            return OptionChain(
                underlying=underlying,
                spot=spot,
                expiry=datetime.utcnow(),
                atm_strike=atm,
                legs=legs,
            )
        except Exception:
            return self._demo_chain(underlying)

    async def get_history(self, symbol: str, resolution: str, from_dt: datetime, to_dt: datetime) -> list[HistoryBar]:
        if not self._fy:
            return []
        try:
            resp = self._fy.history({
                "symbol": symbol,
                "resolution": resolution,
                "date_format": "0",
                "range_from": str(int(from_dt.timestamp())),
                "range_to": str(int(to_dt.timestamp())),
                "cont_flag": "1",
            })
            bars = []
            for candle in (resp.get("candles") or []):
                bars.append(HistoryBar(
                    ts=datetime.fromtimestamp(candle[0]),
                    open=candle[1], high=candle[2], low=candle[3], close=candle[4],
                    volume=candle[5] if len(candle) > 5 else 0,
                    oi=candle[6] if len(candle) > 6 else 0,
                ))
            return bars
        except Exception:
            return []

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_profile(self) -> AccountProfile:
        if not self._fy:
            return AccountProfile("demo", "Demo User", "demo@reyu.ai", "fyers")
        try:
            resp = self._fy.get_profile()
            data = resp.get("data", {})
            funds_resp = self._fy.funds()
            equity = next((f for f in (funds_resp.get("fund_limit") or []) if f.get("id") == 10), {})
            return AccountProfile(
                user_id=data.get("fy_id", ""),
                name=data.get("name", ""),
                email=data.get("email_id", ""),
                broker="fyers",
                funds_available=equity.get("equityAmount", 0.0),
                funds_used=equity.get("utilizedAmount", 0.0),
            )
        except Exception:
            return AccountProfile("demo", "Demo User", "demo@reyu.ai", "fyers")

    async def get_positions(self) -> list[Position]:
        if not self._fy:
            return []
        try:
            resp = self._fy.positions()
            positions = []
            for p in (resp.get("netPositions") or []):
                qty = p.get("netQty", 0)
                avg = p.get("avgPrice", 0.0)
                ltp = p.get("ltp", 0.0)
                pnl = p.get("pl", 0.0)
                positions.append(Position(
                    symbol=p.get("symbol", ""),
                    product=p.get("productType", "INTRADAY"),
                    qty=qty,
                    avg_price=avg,
                    ltp=ltp,
                    pnl=pnl,
                    pnl_pct=((ltp - avg) / avg * 100) if avg else 0.0,
                    side="LONG" if qty > 0 else "SHORT",
                    broker_id="fyers",
                ))
            return positions
        except Exception:
            return []

    async def get_orders(self) -> list[Order]:
        if not self._fy:
            return []
        try:
            resp = self._fy.orderbook()
            orders = []
            for o in (resp.get("orderBook") or []):
                orders.append(Order(
                    order_id=o.get("id", ""),
                    symbol=o.get("symbol", ""),
                    side="BUY" if o.get("side") == 1 else "SELL",
                    qty=o.get("qty", 0),
                    filled_qty=o.get("filledQty", 0),
                    order_type={1: "LIMIT", 2: "MARKET", 3: "SL", 4: "SL-M"}.get(o.get("type"), "MARKET"),
                    price=o.get("limitPrice", 0.0),
                    status=o.get("status", ""),
                    message=o.get("message", ""),
                ))
            return orders
        except Exception:
            return []

    # ── Trading ───────────────────────────────────────────────────────────────

    async def place_order(self, req: OrderRequest) -> Order:
        if req.dry_run or not self._fy:
            return Order(
                order_id=f"DRY-{int(datetime.utcnow().timestamp())}",
                symbol=req.symbol,
                side=req.side,
                qty=req.qty,
                filled_qty=0,
                order_type=req.order_type,
                price=req.price,
                status="DRY_RUN",
                message="Paper trade — not sent to broker",
            )
        try:
            type_map = {"MARKET": 2, "LIMIT": 1, "SL": 4, "SL-M": 3}
            resp = self._fy.place_order({
                "symbol": req.symbol,
                "qty": req.qty,
                "type": type_map.get(req.order_type, 2),
                "side": 1 if req.side == "BUY" else -1,
                "productType": req.product,
                "limitPrice": req.price,
                "stopPrice": req.stop_price,
                "validity": "DAY",
                "filledQty": 0,
            })
            if resp.get("code") != 200:
                raise RuntimeError(resp.get("message", "Order failed"))
            return Order(
                order_id=resp.get("id", ""),
                symbol=req.symbol, side=req.side, qty=req.qty, filled_qty=0,
                order_type=req.order_type, price=req.price, status="OPEN",
            )
        except Exception as e:
            raise RuntimeError(f"Fyers place_order failed: {e}")

    async def cancel_order(self, order_id: str) -> bool:
        if not self._fy:
            return False
        try:
            resp = self._fy.cancel_order({"id": order_id})
            return resp.get("code") == 200
        except Exception:
            return False

    async def get_margin(self, orders: list[OrderRequest]) -> dict:
        if not self._fy:
            return {"total": 0.0, "available": 0.0, "required": 0.0}
        try:
            data = [{"symbol": o.symbol, "qty": o.qty, "side": 1 if o.side == "BUY" else -1,
                     "type": 2, "productType": o.product} for o in orders]
            resp = self._fy.get_basket_margin({"orderData": data})
            return {
                "total": resp.get("equity", {}).get("totalMargin", 0.0),
                "available": resp.get("equity", {}).get("availableMargin", 0.0),
                "required": resp.get("equity", {}).get("utilizedMargin", 0.0),
            }
        except Exception:
            return {"total": 0.0, "available": 0.0, "required": 0.0}

    async def search_symbols(self, query: str) -> list[dict]:
        if not self._fy:
            return []
        try:
            resp = self._fy.symbol_master()
            return [{"symbol": s, "name": s} for s in (resp or []) if query.upper() in s.upper()][:20]
        except Exception:
            return []

    def symbol_for_option(self, underlying: str, expiry: datetime, strike: float, option_type: str) -> str:
        # Fyers format: NSE:NIFTY26JUN2424800CE
        exp_str = expiry.strftime("%d%b%y").upper()
        return f"NSE:{underlying.split(':')[-1].split('-')[0]}{exp_str}{int(strike)}{option_type}"

    # ── Demo mode helpers ─────────────────────────────────────────────────────

    def _demo_quotes(self, symbols: list[str]) -> list[Quote]:
        demo = {"NSE:NIFTY50-INDEX": 24812.0, "NSE:NIFTYBANK-INDEX": 53241.0}
        return [Quote(symbol=s, ltp=demo.get(s, 1000.0)) for s in symbols]

    def _demo_chain(self, underlying: str) -> OptionChain:
        spot = 24812.0
        atm = 24800.0
        legs = []
        for strike in [24600, 24700, 24800, 24900, 25000]:
            for ot in ["CE", "PE"]:
                legs.append(OptionLeg(
                    symbol=f"DEMO:{underlying}:{strike}{ot}",
                    strike=float(strike), expiry=datetime.utcnow(),
                    option_type=ot, oi=100000, ltp=100.0 if ot == "CE" else 80.0, iv=14.0,
                ))
        return OptionChain(underlying=underlying, spot=spot, expiry=datetime.utcnow(), atm_strike=atm, legs=legs)
