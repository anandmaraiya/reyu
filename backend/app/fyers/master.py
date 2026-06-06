"""Fyers symbol-master sync.

Pulls the daily NSE F&O master CSV from Fyers' public CDN and refreshes
lot sizes in the `instruments` table. This is the ground-truth source —
NSE adjusts stock F&O lots quarterly and we don't want to ship stale
hardcoded values into ROI calculations.

CSV columns (positional, comma-delimited, no header):
  0  fytoken
  1  description           e.g. "NIFTY 09 Jun 26 23000 CE"
  2  exch_id
  3  lot_size              ← what we want
  4  tick_size
  5  (reserved)
  6  segment_times
  7  last_updated_date
  8  expiry_unix
  9  fyers_symbol          ← canonical NSE:* form
 10  exchange
 11  segment
 12  scrip_token
 13  underlying            e.g. "NIFTY", "HDFCBANK"
 14  (reserved)
 15  strike (-1 for futures)
 16  option_type (CE/PE/XX)
 …

We process every option/future row and also derive the *underlying*
lot — i.e. attach the lot to the spot/index symbol the user trades from
(`NSE:NIFTY50-INDEX`, `NSE:HDFCBANK-EQ`) so RL ROI calcs can look it up
by underlying without parsing F&O tickers.
"""
from __future__ import annotations

import io
import logging
from collections import Counter
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal, Instrument

log = logging.getLogger("reyu.fyers.master")

NSE_FO_URL = "https://public.fyers.in/sym_details/NSE_FO.csv"
BSE_FO_URL = "https://public.fyers.in/sym_details/BSE_FO.csv"

# Underlying-scrip → spot/index symbol the rest of the codebase keys on.
# For ordinary equities the rule is `NSE:{SCRIP}-EQ`; only the indices
# need explicit mapping because their underlying-field strips the "50"
# / "BANK" / etc. and re-appends as a suffix.
INDEX_UNDERLYING_MAP = {
    "NIFTY":      "NSE:NIFTY50-INDEX",
    "BANKNIFTY":  "NSE:NIFTYBANK-INDEX",
    "FINNIFTY":   "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
    "NIFTYNXT50": "NSE:NIFTYNXT50-INDEX",
}


def _to_spot_symbol(underlying_scrip: str) -> str:
    """Map a master-CSV underlying field to the spot symbol we track."""
    if underlying_scrip in INDEX_UNDERLYING_MAP:
        return INDEX_UNDERLYING_MAP[underlying_scrip]
    return f"NSE:{underlying_scrip}-EQ"


async def fetch_master_csv(url: str = NSE_FO_URL) -> str:
    """Download the master CSV. ~5 MB / ~90k rows for NSE F&O."""
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.text


def parse_lot_sizes(csv_text: str) -> dict[str, dict[str, Any]]:
    """Parse the master CSV into {symbol → info}.

    Two kinds of entries land in the output:
      1. Each F&O leg itself (e.g. NSE:NIFTY2660923000CE) so the order
         router can look up exact lot.
      2. The aggregated *underlying* symbol (NSE:NIFTY50-INDEX,
         NSE:HDFCBANK-EQ) — its lot is set to the modal lot across that
         underlying's chain. Per-strike lots are uniform within an
         underlying so the mode is just "the lot", but using mode is
         robust against any one-off bad row in the CSV.
    """
    out: dict[str, dict[str, Any]] = {}
    underlying_lots: dict[str, Counter] = {}

    rdr = io.StringIO(csv_text)
    for line in rdr:
        parts = line.rstrip("\n").split(",")
        if len(parts) < 14:
            continue
        try:
            lot = int(parts[3])
            tick = float(parts[4]) if parts[4] else 0.05
        except ValueError:
            continue
        if lot <= 0:
            continue
        symbol = parts[9].strip()
        underlying_scrip = parts[13].strip()
        opt_type = parts[16].strip() if len(parts) > 16 else ""
        try:
            strike = float(parts[15]) if len(parts) > 15 and parts[15] else None
        except ValueError:
            strike = None
        if not symbol or not underlying_scrip:
            continue

        out[symbol] = {
            "symbol": symbol,
            "lot_size": lot,
            "tick_size": tick,
            "underlying": underlying_scrip,
            "strike": strike if strike and strike > 0 else None,
            "option_type": opt_type if opt_type in ("CE", "PE") else None,
        }
        underlying_lots.setdefault(underlying_scrip, Counter())[lot] += 1

    # Add the spot symbols with their modal lot
    for scrip, counter in underlying_lots.items():
        modal_lot = counter.most_common(1)[0][0]
        spot = _to_spot_symbol(scrip)
        out[spot] = {
            "symbol": spot,
            "lot_size": modal_lot,
            "tick_size": 0.05,
            "underlying": scrip,
            "strike": None,
            "option_type": None,
        }
    return out


async def sync_lot_sizes(url: str = NSE_FO_URL) -> dict[str, int]:
    """End-to-end refresh: download, parse, upsert into instruments.

    Returns a small summary {fetched, upserted, indices, equities, options}.
    """
    log.info("syncing Fyers symbol master from %s", url)
    csv_text = await fetch_master_csv(url)
    parsed = parse_lot_sizes(csv_text)

    n_index = n_equity = n_option = n_future = 0
    rows: list[dict] = []
    for sym, info in parsed.items():
        if sym.endswith("-INDEX"):
            kind = "INDEX"; n_index += 1
        elif sym.endswith("-EQ"):
            kind = "EQUITY"; n_equity += 1
        elif sym.endswith("CE") or sym.endswith("PE"):
            kind = "OPTION"; n_option += 1
        elif "FUT" in sym:
            kind = "FUTURE"; n_future += 1
        else:
            kind = None
        rows.append({
            "symbol": sym,
            "lot_size": info["lot_size"],
            "tick_size": info["tick_size"],
            "underlying": info["underlying"],
            "strike": info["strike"],
            "option_type": info["option_type"],
            "segment": kind,
        })

    # Batched upsert — single round-trip per chunk. 91k rows in ~2 s.
    BATCH = 2000
    async with SessionLocal() as s:
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            stmt = pg_insert(Instrument).values(chunk).on_conflict_do_update(
                index_elements=[Instrument.symbol],
                set_={
                    "lot_size": pg_insert(Instrument).excluded.lot_size,
                    "tick_size": pg_insert(Instrument).excluded.tick_size,
                },
            )
            await s.execute(stmt)
        await s.commit()
    log.info("master sync done — options=%d futures=%d equities=%d indices=%d",
             n_option, n_future, n_equity, n_index)
    return {
        "fetched": len(parsed),
        "options": n_option, "futures": n_future,
        "equities": n_equity, "indices": n_index,
    }
