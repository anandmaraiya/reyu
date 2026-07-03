"""Reyu analysis skills (task #83) — data tools the LLM calls to ground
its equity / technical / indicator answers in REAL platform data instead
of hallucinating prices.

Skills → tools:
  equity_analysis     — full technical read of a stock/index from daily
                        candles: trend vs SMAs, RSI, 52-week position,
                        volume behaviour, return ladder, key levels.
  indicator_analysis  — recent SERIES for one indicator (close/sma/rsi/
                        volume) so Reyu can describe shape and crossings.
  (option-chain analysis reuses the existing chain tools in tools.py;
   fundamental analysis has NO platform data feed yet — the system prompt
   instructs Reyu to say so rather than invent numbers.)

Everything returned is factual computation; interpretation happens in the
LLM under the no-advice system prompt.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.strategy.equity_features import compute_equity_features, WARMUP_DAYS
from app.strategy.equity_runner import fetch_daily_candles

log = logging.getLogger("reyu.agent.analysis")


def _norm_symbol(raw: str) -> str:
    """Accept 'RELIANCE', 'NSE:RELIANCE', 'reliance-eq' → NSE:RELIANCE-EQ.
    Indices pass through untouched when already suffixed."""
    s = (raw or "").strip().upper()
    if not s:
        return s
    if ":" not in s:
        s = f"NSE:{s}"
    if not (s.endswith("-EQ") or s.endswith("-INDEX")):
        s += "-EQ"
    return s


async def _daily(symbol: str, days: int = 400):
    today = date.today()
    return await fetch_daily_candles(
        symbol, today - timedelta(days=int(days * 1.6) + 30), today,
        min_days=30,
    )


async def t_equity_analysis(args: dict, user: dict | None) -> dict:
    """Structured technical read of one stock/index from daily candles."""
    symbol = _norm_symbol(args.get("symbol") or args.get("underlying") or "")
    if not symbol:
        return {"text": "Which stock? Give me a symbol like RELIANCE or NSE:TCS-EQ."}
    try:
        candles, source = await _daily(symbol)
    except ValueError as e:
        return {"text": f"Couldn't load daily history for {symbol}: {e}"}

    f = compute_equity_features(candles, len(candles) - 1)
    closes = [c[4] for c in candles]
    last = candles[-1]

    def sma(n):
        return round(sum(closes[-n:]) / n, 2) if len(closes) >= n else None

    data = {
        "symbol": symbol,
        "as_of": date.fromtimestamp(last[0] + 19800).isoformat(),
        "history_days": len(candles),
        "source": source,
        "close": round(last[4], 2),
        "day": {"open": round(last[1], 2), "high": round(last[2], 2),
                "low": round(last[3], 2), "volume": int(last[5])},
        "trend": {
            "sma20": sma(20), "sma50": sma(50), "sma200": sma(200),
            "above_sma200": f.get("eq_close_above_sma200") == 1.0,
            "sma20_above_sma50": f.get("eq_sma20_above_sma50") == 1.0,
            "dist_sma20_pct": round(f["eq_sma20_dist_pct"], 2) if "eq_sma20_dist_pct" in f else None,
            "dist_sma200_pct": round(f["eq_sma200_dist_pct"], 2) if "eq_sma200_dist_pct" in f else None,
        },
        "momentum": {
            "rsi_14": f.get("eq_rsi_14"),
            "ret_1d_pct": round(f["eq_ret_1d_pct"], 2) if "eq_ret_1d_pct" in f else None,
            "ret_5d_pct": round(f["eq_ret_5d_pct"], 2) if "eq_ret_5d_pct" in f else None,
            "ret_20d_pct": round(f["eq_ret_20d_pct"], 2) if "eq_ret_20d_pct" in f else None,
        },
        "levels": {
            "dist_52w_high_pct": round(f["eq_high_52w_dist_pct"], 2) if "eq_high_52w_dist_pct" in f else None,
            "dist_52w_low_pct": round(f["eq_low_52w_dist_pct"], 2) if "eq_low_52w_dist_pct" in f else None,
            "dist_20d_high_pct": round(f["eq_high_20d_dist_pct"], 2) if "eq_high_20d_dist_pct" in f else None,
        },
        "volume": {"surge_vs_20d_avg": round(f["eq_volume_surge"], 2) if "eq_volume_surge" in f else None,
                   "gap_today_pct": round(f["eq_gap_pct"], 2) if "eq_gap_pct" in f else None},
    }
    return {
        "text": f"Technical read for {symbol} computed from {len(candles)} daily bars.",
        "data": data,
    }


_INDICATORS = ("close", "sma20", "sma50", "sma200", "rsi14", "volume")


async def t_indicator_analysis(args: dict, user: dict | None) -> dict:
    """Recent daily series for one indicator — lets Reyu describe shape,
    slope, and crossings instead of a single point value."""
    symbol = _norm_symbol(args.get("symbol") or "")
    indicator = (args.get("indicator") or "close").lower().replace("_", "")
    n = min(int(args.get("days") or 30), 90)
    if not symbol:
        return {"text": "Which symbol should I compute indicators for?"}
    if indicator not in _INDICATORS:
        return {"text": f"Unknown indicator `{indicator}`. I can compute: {', '.join(_INDICATORS)}."}
    try:
        candles, source = await _daily(symbol)
    except ValueError as e:
        return {"text": f"Couldn't load daily history for {symbol}: {e}"}

    closes = [c[4] for c in candles]
    series: list[dict] = []
    for i in range(max(0, len(candles) - n), len(candles)):
        d = date.fromtimestamp(candles[i][0] + 19800).isoformat()
        if indicator == "close":
            v = round(candles[i][4], 2)
        elif indicator == "volume":
            v = int(candles[i][5])
        elif indicator.startswith("sma"):
            w = int(indicator[3:])
            v = round(sum(closes[max(0, i - w + 1): i + 1]) / min(w, i + 1), 2) if i + 1 >= w else None
        else:  # rsi14
            f = compute_equity_features(candles, i)
            v = f.get("eq_rsi_14")
        series.append({"date": d, "value": v})

    return {
        "text": f"{indicator} series for {symbol} — last {len(series)} sessions ({source}).",
        "data": {"symbol": symbol, "indicator": indicator, "series": series},
    }
