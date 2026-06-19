"""Intraday options-contract history via Fyers history endpoint.

Fyers exposes the history endpoint for individual contract symbols, e.g.
`NSE:NIFTY2660923000CE`. With 100-day windows at 1-min resolution we can
backfill real intraday premium history without waiting for forward
collection — the single biggest correctness win for backtests.

Symbol format (Fyers v3, weekly expiry):
  NSE:{UNDERLYING}{YY}{M}{DD}{STRIKE}{CE|PE}
where {M} is 1-9, O (oct), N (nov), D (dec).

Strategy:
  1. Resolve underlying spot from recent tick_1m to know ATM band.
  2. Enumerate the last N weekly expiries (Thursdays for NSE) AND the
     next 2 upcoming (for current-week data).
  3. For each (expiry, strike, side) in ATM±10, build Fyers symbol.
  4. Call fy.history() with the trading-day window (≤ 100 days per call,
     so multi-window for longer ranges).
  5. UPSERT candles into option_contract_1m.
  6. Polite delay between calls (Fyers rate-limit safety).

Run via POST /api/data/option-history/backfill.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal, OptionContract1m, Tick1m
from app.fyers import client as fy
from app.fyers.symbols import resolve as resolve_symbol

log = logging.getLogger("reyu.data.option_history")

# NSE weekly expiry month codes used in Fyers symbols
_MONTH_CODE = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "O", "N", "D"]


def _fmt_weekly_symbol(underlying_scrip: str, expiry: date,
                       strike: int, opt: str, exch: str = "NSE") -> str:
    """e.g. NSE:NIFTY2660923000CE for expiry 2026-06-09 strike 23000 CE."""
    yy = expiry.year % 100
    mcode = _MONTH_CODE[expiry.month - 1]
    return f"{exch}:{underlying_scrip}{yy}{mcode}{expiry.day:02d}{int(strike)}{opt}"


def _fmt_monthly_symbol(underlying_scrip: str, expiry: date,
                        strike: int, opt: str, exch: str = "NSE") -> str:
    """e.g. NSE:NIFTY26JUN23000CE for monthly expiry."""
    yy = expiry.year % 100
    mmm = expiry.strftime("%b").upper()
    return f"{exch}:{underlying_scrip}{yy}{mmm}{int(strike)}{opt}"


def _nse_weekly_thursdays(through: date, count: int) -> list[date]:
    """Return the last `count` Thursdays through `through` (inclusive)."""
    d = through
    while d.weekday() != 3:           # 3 = Thursday
        d -= timedelta(days=1)
    out: list[date] = []
    while len(out) < count:
        out.append(d)
        d -= timedelta(days=7)
    return list(reversed(out))


def _next_thursdays(starting_from: date, count: int) -> list[date]:
    d = starting_from
    while d.weekday() != 3:
        d += timedelta(days=1)
    out: list[date] = []
    for _ in range(count):
        out.append(d)
        d += timedelta(days=7)
    return out


async def _spot_from_recent_tick(underlying: str) -> float | None:
    async with SessionLocal() as s:
        row = (await s.execute(
            select(Tick1m).where(Tick1m.symbol == underlying)
            .order_by(Tick1m.ts.desc()).limit(1)
        )).scalar_one_or_none()
        return row.close if row else None


# ── Underlying scrip resolution (Fyers contract naming) ────────────
# Indices with weekly expiries on BSE/NSE
_UNDERLYING_SCRIP = {
    "NSE:NIFTY50-INDEX":   "NIFTY",
    "NSE:NIFTYBANK-INDEX": "BANKNIFTY",
    "NSE:FINNIFTY-INDEX":  "FINNIFTY",
    "NSE:MIDCPNIFTY-INDEX":"MIDCPNIFTY",
    "BSE:SENSEX-INDEX":    "SENSEX",
    "BSE:BANKEX-INDEX":    "BANKEX",
}

# Fyers exchange prefix per underlying — defaults to NSE
_EXCHANGE_PREFIX = {
    "BSE:SENSEX-INDEX": "BSE",
    "BSE:BANKEX-INDEX": "BSE",
}


def _strike_step(underlying: str) -> int:
    u = underlying.upper()
    if "NIFTY50" in u or "FINNIFTY" in u or "MIDCP" in u:
        return 50
    if "BANKNIFTY" in u or "BANKEX" in u or "SENSEX" in u:
        return 100
    if "-EQ" in u:
        return 5
    return 50


# ── Symbol enumeration ─────────────────────────────────────────────
def _resolve_scrip(underlying: str) -> tuple[str, bool]:
    """Map a tracked underlying to (Fyers contract scrip, is_weekly).

    - Indices in `_UNDERLYING_SCRIP`: weekly expiry, returns (scrip, True)
    - `NSE:RELIANCE-EQ` -> ("RELIANCE", False) — stocks use monthly expiry
    - Unsupported indices (BSE BANKEX/SENSEX, NIFTYNXT50) raise.
    """
    if underlying in _UNDERLYING_SCRIP:
        return _UNDERLYING_SCRIP[underlying], True
    if underlying.endswith("-EQ") and underlying.startswith("NSE:"):
        scrip = underlying[4:-3]                     # "NSE:RELIANCE-EQ" -> "RELIANCE"
        return scrip, False
    raise ValueError(f"unsupported underlying {underlying!r} for Fyers contract naming")


def _last_thursday_of_month(year: int, month: int) -> date:
    """NSE monthly expiry is the last Thursday of the month."""
    # Walk backward from the 1st of next month
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    d = nxt - timedelta(days=1)
    while d.weekday() != 3:
        d -= timedelta(days=1)
    return d


def _monthly_expiries(through: date, months_back: int) -> list[date]:
    """Return last `months_back` monthly expiries through `through`."""
    out: list[date] = []
    y, m = through.year, through.month
    for _ in range(months_back):
        out.append(_last_thursday_of_month(y, m))
        m -= 1
        if m == 0:
            m = 12; y -= 1
    return list(reversed(out))


async def enumerate_symbols(
    underlying: str,
    *,
    history_back_days: int = 100,
    forward_weeklies: int = 2,
    strikes_around_atm: int = 10,
) -> tuple[list[str], date]:
    """Return (symbols, today) where symbols is the full list of contracts
    to backfill. Uses recent spot for ATM resolution."""
    scrip, is_weekly = _resolve_scrip(underlying)
    spot = await _spot_from_recent_tick(underlying)
    if not spot:
        # Fall back to a tick-history call to get last close
        today = datetime.utcnow().date()
        hist = await fy.history(underlying, resolution="D",
                                range_from=(today - timedelta(days=10)).isoformat(),
                                range_to=today.isoformat())
        candles = hist.get("candles") or []
        if not candles:
            raise ValueError(f"could not resolve spot for {underlying}")
        spot = candles[-1][4]
    step = _strike_step(underlying)
    atm = round(spot / step) * step

    today = datetime.utcnow().date()
    if is_weekly:
        past = _nse_weekly_thursdays(today, count=history_back_days // 7 + 2)
        future = _next_thursdays(today, count=forward_weeklies)
        expiries = sorted(set(past + future))
    else:
        # Monthly expiries cover much longer horizons per contract
        months_back = max(4, history_back_days // 30 + 1)
        expiries = _monthly_expiries(today, months_back)
        # Add the next 1-2 upcoming months
        cur_m = today + timedelta(days=32)
        expiries.append(_last_thursday_of_month(cur_m.year, cur_m.month))
        expiries = sorted(set(expiries))

    symbols: list[str] = []
    fmt = _fmt_weekly_symbol if is_weekly else _fmt_monthly_symbol
    exch = _EXCHANGE_PREFIX.get(underlying, "NSE")
    for exp in expiries:
        for off in range(-strikes_around_atm, strikes_around_atm + 1):
            strike = atm + off * step
            for opt in ("CE", "PE"):
                symbols.append(fmt(scrip, exp, strike, opt, exch=exch))
    return symbols, today


# ── Backfill core ──────────────────────────────────────────────────
async def backfill_underlying(
    underlying: str,
    *,
    history_back_days: int = 100,
    forward_weeklies: int = 2,
    strikes_around_atm: int = 10,
    polite_delay_sec: float = 0.3,
) -> dict:
    """Pull 1-min history for every contract in the ATM band over the
    target window. Returns counts. UPSERT-idempotent so re-running just
    fills gaps."""
    symbols, today = await enumerate_symbols(
        underlying,
        history_back_days=history_back_days,
        forward_weeklies=forward_weeklies,
        strikes_around_atm=strikes_around_atm,
    )
    log.info("option-history %s: %d contracts to fetch", underlying, len(symbols))

    inserted = 0
    failed = 0
    skipped_empty = 0
    skipped_dead = 0       # contract expired before requested window
    skipped_tainted = 0    # Fyers returned underlying spot instead of premium
    start = today - timedelta(days=history_back_days)
    end = today

    for i, sym in enumerate(symbols):
        # Parse symbol up-front so we can clamp the request window to the
        # contract's actual trading life. This is the single most important
        # guard against Fyers' silent underlying-substitution behavior:
        # asking for past-100d history of a long-dead contract returns the
        # underlying spot. The contract only existed between (listing, expiry).
        meta = _parse_monthly_symbol(sym) or _parse_weekly_symbol(sym)
        if not meta:
            skipped_empty += 1
            continue
        scrip, expiry_date, strike, opt = meta

        # (1) Hard guard: contract dead before window starts → no real data exists.
        if expiry_date < start:
            skipped_dead += 1
            continue

        # Clamp range_to to expiry (Fyers will substitute spot for post-expiry days).
        req_to = min(end, expiry_date)
        req_from = start

        try:
            hist = await fy.history(
                sym, resolution="1",
                range_from=req_from.isoformat(), range_to=req_to.isoformat(),
            )
        except Exception as e:
            failed += 1
            log.debug("history %s failed: %s", sym, e)
            await asyncio.sleep(polite_delay_sec)
            continue
        candles = hist.get("candles") or []
        if not candles:
            skipped_empty += 1
            await asyncio.sleep(polite_delay_sec)
            continue

        # (2) Premium sanity: option premium can never reasonably be >50% of
        # strike (deep-ITM is the only case it gets close, and ATM premium is
        # typically 1-3% of strike). When Fyers substitutes underlying spot,
        # close ≈ strike → median/strike ≈ 1.0 → reject loudly.
        closes = [c[4] for c in candles if c[4]]
        if closes:
            median_close = sorted(closes)[len(closes) // 2]
            # Threshold 0.3 = premium > 30% of strike. Real-world ceiling: deep-ITM
            # CE intrinsic = (spot-strike). For spot 1.3× strike, intrinsic = 0.3×strike
            # — beyond that point a contract is far enough ITM that we usually
            # wouldn't be backfilling it anyway (it's not in ATM±10). The Fyers
            # substitution signature is median_close ≈ spot ≈ strike (ratio ~1).
            if strike > 0 and median_close > 0.3 * strike:
                skipped_tainted += 1
                log.warning(
                    "option-history %s: REJECTED — median close %.2f vs strike %d "
                    "(ratio %.2f) — Fyers likely returned underlying spot",
                    sym, median_close, strike, median_close / strike,
                )
                await asyncio.sleep(polite_delay_sec)
                continue

        rows = []
        for c in candles:
            ts = datetime.utcfromtimestamp(c[0])
            rows.append({
                "ts": ts, "symbol": sym,
                "underlying": underlying,
                "strike": float(strike),
                "expiry": datetime.combine(expiry_date, datetime.min.time()),
                "option_type": opt,
                "open": c[1], "high": c[2], "low": c[3], "close": c[4],
                "volume": int(c[5] or 0),
                "oi": int(c[6] or 0) if len(c) > 6 else 0,
            })
        async with SessionLocal() as s:
            BATCH = 2000
            for j in range(0, len(rows), BATCH):
                await s.execute(
                    pg_insert(OptionContract1m).values(rows[j:j + BATCH])
                    .on_conflict_do_nothing()
                )
            await s.commit()
        inserted += len(rows)

        if (i + 1) % 25 == 0:
            log.info("option-history %s: %d/%d contracts, %d candles so far",
                     underlying, i + 1, len(symbols), inserted)
        await asyncio.sleep(polite_delay_sec)

    return {
        "underlying": underlying,
        "contracts_requested": len(symbols),
        "candles_inserted": inserted,
        "contracts_failed": failed,
        "contracts_empty": skipped_empty,
        "contracts_dead_before_window": skipped_dead,
        "contracts_tainted_spot_substitution": skipped_tainted,
        "window": f"{start.isoformat()}..{end.isoformat()}",
    }


# ── Symbol parser (back-direction) ─────────────────────────────────
_MMM_MAP = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
            "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}


def _parse_monthly_symbol(sym: str) -> tuple[str, date, int, str] | None:
    """Inverse of _fmt_monthly_symbol. Returns (scrip, expiry, strike, opt).
    Format: NSE:{SCRIP}{YY}{MMM}{STRIKE}{CE|PE} eg NSE:RELIANCE25JUN1200CE"""
    if not sym.startswith("NSE:") or sym[-2:] not in ("CE", "PE"):
        return None
    opt = sym[-2:]
    body = sym[4:-2]
    i = 0
    while i < len(body) and body[i].isalpha():
        i += 1
    scrip = body[:i]
    rest = body[i:]
    if len(rest) < 5:
        return None
    yy = rest[0:2]
    mmm = rest[2:5]
    if not yy.isdigit() or mmm.upper() not in _MMM_MAP:
        return None
    strike_str = rest[5:]
    if not strike_str.isdigit():
        return None
    try:
        expiry = _last_thursday_of_month(2000 + int(yy), _MMM_MAP[mmm.upper()])
    except ValueError:
        return None
    return scrip, expiry, int(strike_str), opt


def _parse_weekly_symbol(sym: str) -> tuple[str, date, int, str] | None:
    """Inverse of `_fmt_weekly_symbol`. Returns (scrip, expiry, strike, opt)."""
    if not sym.startswith("NSE:") or sym[-2:] not in ("CE", "PE"):
        return None
    opt = sym[-2:]
    body = sym[4:-2]                       # strip "NSE:" and "CE/PE"
    # Find where alpha (scrip) ends
    i = 0
    while i < len(body) and body[i].isalpha():
        i += 1
    scrip = body[:i]
    rest = body[i:]
    if len(rest) < 5:
        return None
    yy = int(rest[0:2]) + 2000
    mcode = rest[2]
    if mcode in _MONTH_CODE:
        month = _MONTH_CODE.index(mcode) + 1
    elif mcode.isdigit():
        month = int(mcode)
    else:
        return None
    dd = rest[3:5]
    if not dd.isdigit():
        return None
    day = int(dd)
    try:
        expiry = date(yy, month, day)
    except ValueError:
        return None
    strike_str = rest[5:]
    if not strike_str.isdigit():
        return None
    return scrip, expiry, int(strike_str), opt
