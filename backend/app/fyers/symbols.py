"""Fyers symbol parsing + lot-size resolution.

Fyers v3 symbol grammar:
  EXCHANGE:SCRIP-SEGMENT          equity        NSE:RELIANCE-EQ
  EXCHANGE:SCRIPYYMONDDSTRIKE{CE|PE}   options  NSE:NIFTY25JAN24800CE
  EXCHANGE:SCRIPYYMMMFUT            futures     NSE:NIFTY25JANFUT
  NSE:NIFTY50-INDEX / NSE:NIFTYBANK-INDEX        indices (not tradable)

Lot sizes change quarterly for stock F&O; index lots are stable. We resolve
in order: (1) Instrument table override, (2) hardcoded index map,
(3) suffix-based default for non-derivatives (1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from app.db import SessionLocal, Instrument


InstrumentType = Literal["EQUITY", "INDEX", "OPTION", "FUTURE", "UNKNOWN"]

# Current NSE index F&O lot sizes (Jan 2026 — verify on https://www.nseindia.com).
INDEX_LOTS = {
    "NIFTY": 75,
    "BANKNIFTY": 30,
    "FINNIFTY": 65,
    "MIDCPNIFTY": 120,
    "NIFTYNXT50": 25,
    "SENSEX": 20,
    "BANKEX": 30,
}

OPTION_RE = re.compile(r"^([A-Z]+):([A-Z]+)(\d{2}[A-Z0-9]{3,5})(\d+)(CE|PE)$")
FUTURE_RE = re.compile(r"^([A-Z]+):([A-Z]+)(\d{2}[A-Z]{3})FUT$")
EQUITY_RE = re.compile(r"^([A-Z]+):([A-Z0-9&-]+)-EQ$")
INDEX_RE = re.compile(r"^([A-Z]+):([A-Z0-9]+)-INDEX$")


@dataclass
class SymbolInfo:
    symbol: str
    instrument: InstrumentType
    underlying: str | None
    strike: float | None
    option_type: str | None       # CE / PE
    lot_size: int
    tick_size: float
    is_tradable: bool


def parse(symbol: str) -> SymbolInfo:
    symbol = symbol.strip().upper()

    if m := OPTION_RE.match(symbol):
        _, scrip, _expiry, strike, opt = m.groups()
        return SymbolInfo(symbol, "OPTION", scrip, float(strike), opt,
                          INDEX_LOTS.get(scrip, 0), 0.05, True)

    if m := FUTURE_RE.match(symbol):
        _, scrip, _expiry = m.groups()
        return SymbolInfo(symbol, "FUTURE", scrip, None, None,
                          INDEX_LOTS.get(scrip, 0), 0.05, True)

    if m := EQUITY_RE.match(symbol):
        return SymbolInfo(symbol, "EQUITY", None, None, None, 1, 0.05, True)

    if m := INDEX_RE.match(symbol):
        return SymbolInfo(symbol, "INDEX", None, None, None, 0, 0.05, False)

    return SymbolInfo(symbol, "UNKNOWN", None, None, None, 1, 0.05, True)


async def resolve(symbol: str) -> SymbolInfo:
    """Same as parse() but the Instrument DB row (if any) overrides lot/tick."""
    info = parse(symbol)
    async with SessionLocal() as s:
        row = (await s.execute(
            select(Instrument).where(Instrument.symbol == symbol)
        )).scalar_one_or_none()
        if row:
            if row.lot_size and row.lot_size > 0:
                info.lot_size = row.lot_size
            if row.tick_size and row.tick_size > 0:
                info.tick_size = row.tick_size
    return info
