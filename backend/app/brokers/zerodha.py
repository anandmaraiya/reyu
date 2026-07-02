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
        """Kite doesn't expose a single chain endpoint. We:
          1. Load the NFO instruments dump (cached daily in Redis)
          2. Filter to (name == underlying, expiry == target)
          3. Batch-quote the ATM ± 15 strikes
          4. Normalise to OptionChain
        """
        if not self._kite:
            raise RuntimeError("Zerodha not connected")

        # Underlying naming: 'NIFTY' etc. — strip our NSE:/-INDEX conventions
        u = underlying.upper().replace("NSE:", "").replace("BSE:", "").replace("-INDEX", "").replace("-EQ", "")
        if u.startswith("NIFTY") and "BANK" not in u and u != "NIFTY":
            # NSE:NIFTY50-INDEX → NIFTY
            u = "NIFTY"

        instruments = await self._nfo_instruments()
        matching = [i for i in instruments if i.get("name") == u]
        if not matching:
            raise RuntimeError(f"No NFO instruments found for underlying {u!r}")

        # Pick target expiry — nearest weekly if not specified
        expiries = sorted({i["expiry"] for i in matching if i.get("expiry")})
        if not expiries:
            raise RuntimeError("No expiries in instruments dump")
        target_expiry = expiry.date() if expiry else expiries[0]
        legs_for_exp = [i for i in matching if i.get("expiry") == target_expiry]
        if not legs_for_exp:
            target_expiry = expiries[0]
            legs_for_exp = [i for i in matching if i.get("expiry") == target_expiry]

        # Spot from an underlying quote — LTPs give us ATM band
        spot_symbol = f"NSE:{u}" if u.endswith("BANK") or u in ("NIFTY", "FINNIFTY") else f"NSE:{u}"
        try:
            spot_data = await run_in_threadpool(self._kite.ltp, [spot_symbol])
            spot = float((spot_data.get(spot_symbol) or {}).get("last_price") or 0)
        except Exception:
            spot = 0.0

        # ATM band: sort strikes, find closest to spot, take ±15
        strikes = sorted({i["strike"] for i in legs_for_exp if i.get("strike")})
        if not strikes or not spot:
            atm_strike = strikes[len(strikes) // 2] if strikes else 0.0
        else:
            atm_strike = min(strikes, key=lambda k: abs(k - spot))
        try:
            idx = strikes.index(atm_strike)
        except ValueError:
            idx = len(strikes) // 2
        band = set(strikes[max(0, idx - 15): idx + 16])

        # Batch quote for the whole band × CE/PE
        symbols_to_quote = [
            f"NFO:{i['tradingsymbol']}"
            for i in legs_for_exp
            if i.get("strike") in band and i.get("instrument_type") in ("CE", "PE")
        ]
        quotes: dict = {}
        if symbols_to_quote:
            try:
                # Kite caps quote() at ~500 symbols per call — chunk defensively
                CHUNK = 250
                for i in range(0, len(symbols_to_quote), CHUNK):
                    q = await run_in_threadpool(self._kite.quote, symbols_to_quote[i:i + CHUNK])
                    quotes.update(q)
            except Exception as e:
                log.warning("kite.quote (chain) failed: %s", e)

        # Build OptionLegs
        legs: list[OptionLeg] = []
        exp_dt = datetime.combine(target_expiry, datetime.min.time())
        for inst in legs_for_exp:
            strike = inst.get("strike")
            if strike not in band:
                continue
            opt_type = inst.get("instrument_type", "")
            if opt_type not in ("CE", "PE"):
                continue
            q = quotes.get(f"NFO:{inst['tradingsymbol']}") or {}
            legs.append(OptionLeg(
                symbol=f"NFO:{inst['tradingsymbol']}",
                strike=float(strike),
                expiry=exp_dt,
                option_type=opt_type,
                oi=int(q.get("oi") or 0),
                oi_change=int(q.get("oi_day_change") or 0),
                volume=int(q.get("volume") or 0),
                ltp=float(q.get("last_price") or 0),
            ))

        return OptionChain(
            underlying=underlying,
            spot=spot,
            expiry=exp_dt,
            atm_strike=float(atm_strike),
            legs=legs,
        )

    async def _instrument_token(self, symbol: str) -> int | None:
        """Reverse-lookup an instrument_token from an NFO or NSE symbol.
        Uses the same cached instruments dump used by option_chain."""
        # Strip exchange prefix
        ts = symbol.split(":", 1)[-1]
        # Try NFO first (options/futures), then NSE (equities)
        for exchange in ("NFO", "NSE"):
            if exchange == "NFO":
                dump = await self._nfo_instruments()
            else:
                # NSE equity instruments — cached separately
                from app.store import store
                import json as _json
                raw = await store.r.get("zerodha:instruments:NSE")
                dump = _json.loads(raw.decode() if isinstance(raw, bytes) else raw) if raw else []
                if not dump and self._kite:
                    try:
                        dump = await run_in_threadpool(self._kite.instruments, "NSE")
                        # Serialise + cache
                        serialisable = []
                        for d in dump:
                            item = dict(d)
                            if hasattr(item.get("expiry"), "isoformat"):
                                item["expiry"] = item["expiry"].isoformat()
                            serialisable.append(item)
                        await store.r.set(
                            "zerodha:instruments:NSE",
                            _json.dumps(serialisable), ex=12 * 3600,
                        )
                    except Exception as e:
                        log.warning("kite.instruments(NSE) failed: %s", e)
                        continue
            for inst in dump:
                if inst.get("tradingsymbol") == ts:
                    tok = inst.get("instrument_token")
                    if tok:
                        return int(tok)
        return None

    async def _nfo_instruments(self) -> list[dict]:
        """Load & cache the NFO instruments dump. Refreshes daily in Redis
        since NSE publishes updated contracts weekly."""
        from app.store import store
        CACHE_KEY = "zerodha:instruments:NFO"
        raw = await store.r.get(CACHE_KEY)
        if raw:
            import json as _json
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode()
                return _json.loads(raw)
            except Exception:
                pass

        # Fetch fresh — kite.instruments returns a big list of dicts
        if not self._kite:
            return []
        try:
            data = await run_in_threadpool(self._kite.instruments, "NFO")
        except Exception as e:
            log.warning("kite.instruments failed: %s", e)
            return []

        # Kite gives datetime objects in `expiry` — serialise for JSON
        import json as _json
        serialisable = []
        for d in data:
            item = dict(d)
            if hasattr(item.get("expiry"), "isoformat"):
                item["expiry"] = item["expiry"].isoformat()
            serialisable.append(item)

        # 12h TTL — refresh twice daily to catch new contracts
        await store.r.set(CACHE_KEY, _json.dumps(serialisable), ex=12 * 3600)

        # Return post-hydration (parse the expiry strings back to date)
        from datetime import date as _date
        for item in data:
            exp = item.get("expiry")
            if isinstance(exp, str):
                try:
                    item["expiry"] = _date.fromisoformat(exp)
                except Exception:
                    pass
        return data

    async def get_history(self, symbol: str, resolution: str, from_dt: datetime, to_dt: datetime) -> list[HistoryBar]:
        if not self._kite:
            return []
        interval_map = {"1": "minute", "5": "5minute", "15": "15minute", "D": "day"}
        # Kite historical_data needs an instrument_token, not a tradingsymbol.
        # We look it up from the cached instruments dump.
        token = await self._instrument_token(symbol)
        if not token:
            log.warning("no instrument_token for %s — historical skipped", symbol)
            return []
        try:
            data = await run_in_threadpool(
                self._kite.historical_data, token, from_dt, to_dt,
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
