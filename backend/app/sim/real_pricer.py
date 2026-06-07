"""Real options-premium pricer — Sprint 1.6.

Replaces the BS-synthetic pricer in `app/sim/engine.py` for backtests
where `option_contract_1m` has data.

Design: bulk-load all candidate rows for a *session window* into memory,
then expose a sync `price(spot, strike, T, opt, ctx) -> float` callable
matching the existing `PricerFn` signature. The simulator engine doesn't
need async or per-bar DB calls — the cache scales with session length,
not bar count.

Strike + expiry resolution: caller passes the strike and the engine
derives the expiry from `ctx["expiry"]`. Falls through to `bs_pricer`
when no real data exists for that bar — the run's `data_quality.source_mix`
records which fraction was real vs synthesised.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.db import SessionLocal, OptionContract1m
from app.sim.engine import bs_pricer

log = logging.getLogger("reyu.sim.real_pricer")


class RealPricerCache:
    """Bulk-loaded real-premium lookup for one session.

    Usage:
        rpc = RealPricerCache(underlying, expiry_dt)
        await rpc.load(window_start_utc, window_end_utc)
        # Pass `rpc.price` as the pricer to simulate_session
    """

    def __init__(self, underlying: str, expiry: datetime):
        self.underlying = underlying
        self.expiry = expiry
        # idx[(strike, opt_type, minute_ts)] -> close
        self._idx: dict[tuple[float, str, datetime], float] = {}
        self.real_hits = 0
        self.bs_fallbacks = 0
        self.window_start: datetime | None = None
        self.window_end: datetime | None = None

    async def load(self, start_ts: datetime, end_ts: datetime) -> int:
        """Load all rows for the expiry window. Returns row count."""
        self.window_start = start_ts.replace(second=0, microsecond=0)
        self.window_end = end_ts.replace(second=0, microsecond=0)
        async with SessionLocal() as s:
            rows = (await s.execute(
                select(OptionContract1m).where(
                    OptionContract1m.underlying == self.underlying,
                    OptionContract1m.expiry == self.expiry,
                    OptionContract1m.ts >= self.window_start,
                    OptionContract1m.ts <= self.window_end,
                )
            )).scalars().all()
        for r in rows:
            key = (r.strike, r.option_type, r.ts.replace(second=0, microsecond=0))
            self._idx[key] = r.close
        log.debug("real_pricer loaded %d rows for %s expiry=%s",
                  len(rows), self.underlying, self.expiry)
        return len(rows)

    def price(self, spot: float, strike: float, T: float,
              opt: str, ctx: dict) -> float:
        """Sync pricer matching `PricerFn` signature.

        `ctx` must include `ts` (epoch seconds or datetime). Falls back
        to `bs_pricer` if no real row matches the bar's minute.
        """
        ts_raw = ctx.get("ts")
        if ts_raw is None:
            self.bs_fallbacks += 1
            return bs_pricer(spot, strike, T, opt, ctx)
        ts = (datetime.utcfromtimestamp(ts_raw)
              if isinstance(ts_raw, (int, float)) else ts_raw)
        minute = ts.replace(second=0, microsecond=0)
        real = self._idx.get((strike, opt, minute))
        if real is None:
            # Try the prior minute (markets fill candles at start, so a
            # 12:05 lookup might want the 12:04 close if 12:05 hasn't formed)
            real = self._idx.get((strike, opt, minute - timedelta(minutes=1)))
        if real is None or real <= 0:
            self.bs_fallbacks += 1
            return bs_pricer(spot, strike, T, opt, ctx)
        self.real_hits += 1
        return real

    def coverage(self) -> dict:
        total = self.real_hits + self.bs_fallbacks
        if total == 0:
            return {"real_pct": 0, "bs_pct": 0, "total_calls": 0}
        return {
            "real_pct": round(self.real_hits / total * 100, 2),
            "bs_pct": round(self.bs_fallbacks / total * 100, 2),
            "total_calls": total,
            "real_hits": self.real_hits,
            "bs_fallbacks": self.bs_fallbacks,
        }


# ── Convenience: build a cache covering a session's candle window ──
async def build_session_cache(
    underlying: str, expiry: datetime,
    candles_5m: list[list],
    pad_minutes: int = 5,
) -> RealPricerCache:
    """Given a candle list and target expiry, pull just the rows we'll
    need for this session. Pads ±5 min so prior-minute fallback still
    has data near session edges."""
    if not candles_5m:
        return RealPricerCache(underlying, expiry)
    start_unix = candles_5m[0][0]
    end_unix = candles_5m[-1][0]
    start = datetime.utcfromtimestamp(start_unix) - timedelta(minutes=pad_minutes)
    end = datetime.utcfromtimestamp(end_unix) + timedelta(minutes=pad_minutes)
    cache = RealPricerCache(underlying, expiry)
    await cache.load(start, end)
    return cache
