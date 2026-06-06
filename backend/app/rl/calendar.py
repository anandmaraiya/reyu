"""Trading-calendar helpers — used by the live RL decide cycle to skip
weekends and out-of-session hours, and by backfill to iterate trading days.

We deliberately don't bake in a holiday list here — Fyers' historical
endpoint returns no candles on holidays, which the backfill loop treats as
"no data, skip the day". Add a static NSE holiday set later if needed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, date

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN_IST = (9, 15)          # 09:15 IST
MARKET_CLOSE_IST = (15, 30)        # 15:30 IST


def now_ist(now: datetime | None = None) -> datetime:
    n = now or datetime.utcnow().replace(tzinfo=timezone.utc)
    return n.astimezone(IST)


def is_trading_day(d: date) -> bool:
    """Mon–Fri. Holidays not yet modelled — Fyers returns empty candles for
    holidays so downstream code degrades gracefully."""
    return d.weekday() < 5


def is_trading_hours(now: datetime | None = None) -> bool:
    """True iff `now` is within 09:15–15:30 IST on a weekday."""
    ist = now_ist(now)
    if not is_trading_day(ist.date()):
        return False
    minutes = ist.hour * 60 + ist.minute
    return (MARKET_OPEN_IST[0] * 60 + MARKET_OPEN_IST[1]) <= minutes <= (MARKET_CLOSE_IST[0] * 60 + MARKET_CLOSE_IST[1])


def market_open_utc(d: date) -> datetime:
    """09:15 IST → UTC naïve for the given trading date."""
    return datetime(d.year, d.month, d.day, MARKET_OPEN_IST[0], MARKET_OPEN_IST[1], tzinfo=IST).astimezone(timezone.utc).replace(tzinfo=None)


def market_close_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, MARKET_CLOSE_IST[0], MARKET_CLOSE_IST[1], tzinfo=IST).astimezone(timezone.utc).replace(tzinfo=None)


def iter_trading_days(start: date, end: date):
    """Yield trading dates (Mon–Fri) from `start` (inclusive) to `end` (inclusive)."""
    d = start
    while d <= end:
        if is_trading_day(d):
            yield d
        d += timedelta(days=1)
