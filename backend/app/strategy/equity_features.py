"""Equity feature vocabulary — daily-bar features for EQUITY_EOD strategies.

The options condition vocabulary (app.rl.features.FEATURE_NAMES) is
chain-derived (PCR, OI, IV…) and meaningless for cash equities. This
module defines the equity-native namespace: classic price/volume
technicals computed from daily OHLCV candles with NO lookahead — every
feature at day `i` uses only data up to and including day `i`'s close.

Candle format matches app.fyers.cache.get_candles:
    [epoch_ts, open, high, low, close, volume]

Used by:
  * app.strategy.spec — Condition feature whitelist (union with options names)
  * app.strategy.equity_runner — backtest feature computation per day
"""
from __future__ import annotations

from typing import Sequence

EQUITY_FEATURE_NAMES: list[str] = [
    "eq_close",                 # raw close (for absolute-price conditions)
    "eq_sma20_dist_pct",        # (close - SMA20) / SMA20 * 100
    "eq_sma50_dist_pct",
    "eq_sma200_dist_pct",
    "eq_sma20_above_sma50",     # 1.0 if SMA20 > SMA50 else 0.0 (golden/death cross via crosses_above)
    "eq_close_above_sma200",    # 1.0 / 0.0 — long-term trend filter
    "eq_rsi_14",                # Wilder RSI, 0..100
    "eq_high_52w_dist_pct",     # (close - 52w high) / 52w high * 100  (≤ 0 near highs)
    "eq_low_52w_dist_pct",      # (close - 52w low) / 52w low * 100    (≥ 0 above lows)
    "eq_high_20d_dist_pct",     # breakout proximity to 20-day high
    "eq_volume_surge",          # today's volume / 20-day avg volume
    "eq_gap_pct",               # (open - prev close) / prev close * 100
    "eq_ret_1d_pct",
    "eq_ret_5d_pct",
    "eq_ret_20d_pct",
]

# Minimum history (trading days) needed before features are reliable.
# SMA200 + 52-week lookback dominate.
WARMUP_DAYS = 252


def _sma(closes: Sequence[float], n: int) -> float | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _rsi14(closes: Sequence[float]) -> float | None:
    """Wilder-smoothed RSI over the last 14 changes."""
    n = 14
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(-n, 0):
        chg = closes[i] - closes[i - 1]
        if chg >= 0:
            gains += chg
        else:
            losses -= chg
    avg_gain, avg_loss = gains / n, losses / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def compute_equity_features(candles: Sequence[Sequence[float]], idx: int) -> dict[str, float]:
    """Feature dict at day `idx` (0-based into `candles`). Uses only
    candles[0..idx]. Missing features (insufficient warmup) are omitted
    from the dict — the condition evaluator treats a missing feature as
    'condition not satisfiable today' rather than erroring the run."""
    window = candles[: idx + 1]
    closes = [c[4] for c in window]
    highs = [c[2] for c in window]
    lows = [c[3] for c in window]
    vols = [c[5] for c in window]
    close = closes[-1]
    out: dict[str, float] = {"eq_close": close}

    for n, name in ((20, "eq_sma20_dist_pct"), (50, "eq_sma50_dist_pct"), (200, "eq_sma200_dist_pct")):
        sma = _sma(closes, n)
        if sma:
            out[name] = (close - sma) / sma * 100.0

    sma20, sma50, sma200 = _sma(closes, 20), _sma(closes, 50), _sma(closes, 200)
    if sma20 is not None and sma50 is not None:
        out["eq_sma20_above_sma50"] = 1.0 if sma20 > sma50 else 0.0
    if sma200 is not None:
        out["eq_close_above_sma200"] = 1.0 if close > sma200 else 0.0

    rsi = _rsi14(closes)
    if rsi is not None:
        out["eq_rsi_14"] = round(rsi, 2)

    lb = min(len(window), 252)
    hi_52w, lo_52w = max(highs[-lb:]), min(lows[-lb:])
    if hi_52w > 0:
        out["eq_high_52w_dist_pct"] = (close - hi_52w) / hi_52w * 100.0
    if lo_52w > 0:
        out["eq_low_52w_dist_pct"] = (close - lo_52w) / lo_52w * 100.0

    if len(window) >= 20:
        hi_20d = max(highs[-20:])
        if hi_20d > 0:
            out["eq_high_20d_dist_pct"] = (close - hi_20d) / hi_20d * 100.0
        avg_vol = sum(vols[-20:]) / 20
        if avg_vol > 0:
            out["eq_volume_surge"] = vols[-1] / avg_vol

    if len(window) >= 2:
        prev_close = closes[-2]
        if prev_close > 0:
            out["eq_gap_pct"] = (window[-1][1] - prev_close) / prev_close * 100.0
            out["eq_ret_1d_pct"] = (close - prev_close) / prev_close * 100.0
    for n, name in ((5, "eq_ret_5d_pct"), (20, "eq_ret_20d_pct")):
        if len(closes) >= n + 1 and closes[-(n + 1)] > 0:
            out[name] = (close - closes[-(n + 1)]) / closes[-(n + 1)] * 100.0

    return out
