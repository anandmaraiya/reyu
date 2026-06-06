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

# Fallback lot sizes — DB rows (synced from Fyers via /api/rl/sync-lot-sizes)
# override these. Kept in sync with the master CSV as of Jun 2026; refresh
# whenever NSE pushes quarterly contract specs.
INDEX_LOTS = {
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "FINNIFTY": 60,
    "MIDCPNIFTY": 120,
    "NIFTYNXT50": 25,
    "SENSEX": 20,
    "BANKEX": 30,
}

FUTURE_RE = re.compile(r"^([A-Z]+):([A-Z]+)(\d{2}[A-Z]{3})FUT$")
EQUITY_RE = re.compile(r"^([A-Z]+):([A-Z0-9&-]+)-EQ$")
INDEX_RE = re.compile(r"^([A-Z]+):([A-Z0-9]+)-INDEX$")


def _parse_option(symbol: str):
    """Parse a Fyers option symbol.

    Fyers v3 uses two formats interchangeably, both with a fixed 5-char
    expiry block sitting between the underlying letters and the strike:
      Monthly:  NSE:NIFTY25JAN24800CE  → expiry "25JAN" (YY + MMM)
      Weekly:   NSE:NIFTY2660923450CE  → expiry "26609" (YY + M + DD where M
                                                          is the month code: 1-9, O, N, D)

    Because the weekly expiry is all-digits, naively walking the trailing
    digit run absorbs the expiry into the strike. We instead grab the 5
    chars immediately after the alphabetic underlying as the expiry block,
    then the digit run after that is the strike.
    """
    if len(symbol) < 6 or symbol[-2:] not in ("CE", "PE"):
        return None
    if ":" not in symbol:
        return None
    opt = symbol[-2:]
    body = symbol[:-2]
    exch, _, after = body.partition(":")
    if not after:
        return None
    j = 0
    while j < len(after) and after[j].isalpha():
        j += 1
    underlying = after[:j]
    # 5-char expiry block, then strike digits
    rest = after[j:]
    if len(rest) < 6:                     # need 5 expiry + ≥1 strike digit
        return None
    expiry = rest[:5]
    strike_str = rest[5:]
    if not strike_str.isdigit():
        return None
    return exch, underlying, float(strike_str), opt, expiry


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

    if parsed := _parse_option(symbol):
        _exch, scrip, strike, opt, _expiry = parsed
        return SymbolInfo(symbol, "OPTION", scrip, strike, opt,
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
