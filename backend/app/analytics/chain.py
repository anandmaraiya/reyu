"""Normalise a Fyers option-chain payload into a tidy structure with PCR, OI
change, max-pain and per-strike Greeks suitable for a single-view dashboard.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.analytics.greeks import greeks, implied_vol

RISK_FREE = 0.07  # India 10Y proxy


def _years_to_expiry(expiry_ts: int | str | None) -> float:
    if not expiry_ts:
        return 7 / 365
    try:
        ts = int(expiry_ts)
        secs = ts - datetime.utcnow().timestamp()
        return max(secs / (365 * 24 * 3600), 1 / 365)
    except Exception:
        return 7 / 365


def normalize_chain(payload: dict[str, Any]) -> dict[str, Any]:
    """Accepts the raw payload returned by fyersModel.optionchain.

    Returns:
        {
          underlying, ltp, expiry, strikes: [{strike, ce:{...}, pe:{...}}],
          summary: {pcr_oi, pcr_volume, max_pain, total_ce_oi, total_pe_oi,
                    ce_oi_change, pe_oi_change, atm_iv}
        }
    """
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    chain = data.get("optionsChain", []) or []
    underlying = next((c for c in chain if c.get("option_type") in ("", None)), {})
    spot = underlying.get("ltp") or data.get("ltp") or 0
    expiry_ts = data.get("expiry") or data.get("expiryData", [{}])[0].get("expiry")
    T = _years_to_expiry(expiry_ts)

    strikes: dict[float, dict[str, Any]] = {}
    for row in chain:
        k = row.get("strike_price")
        if not k or row.get("option_type") not in ("CE", "PE"):
            continue
        side = row["option_type"].lower()
        ltp = row.get("ltp", 0) or 0
        iv = row.get("iv") or implied_vol(ltp, spot, k, T, RISK_FREE, row["option_type"])
        g = greeks(spot, k, T, RISK_FREE, iv or 0.2, row["option_type"]) if spot and iv else None
        leg = {
            "ltp": ltp,
            "oi": row.get("oi", 0) or 0,
            "oi_change": row.get("oich", 0) or 0,
            "volume": row.get("volume", 0) or 0,
            "iv": iv,
            "delta": g.delta if g else None,
            "gamma": g.gamma if g else None,
            "theta": g.theta if g else None,
            "vega": g.vega if g else None,
            "symbol": row.get("symbol"),
        }
        strikes.setdefault(k, {"strike": k})[side] = leg

    rows = sorted(strikes.values(), key=lambda r: r["strike"])

    total_ce_oi = sum((r.get("ce", {}).get("oi", 0) for r in rows))
    total_pe_oi = sum((r.get("pe", {}).get("oi", 0) for r in rows))
    total_ce_vol = sum((r.get("ce", {}).get("volume", 0) for r in rows))
    total_pe_vol = sum((r.get("pe", {}).get("volume", 0) for r in rows))
    ce_oi_change = sum((r.get("ce", {}).get("oi_change", 0) for r in rows))
    pe_oi_change = sum((r.get("pe", {}).get("oi_change", 0) for r in rows))

    # Max pain: strike that minimises total writer payout
    def pain(K: float) -> float:
        total = 0.0
        for r in rows:
            s = r["strike"]
            total += max(s - K, 0) * r.get("ce", {}).get("oi", 0)
            total += max(K - s, 0) * r.get("pe", {}).get("oi", 0)
        return total

    max_pain = min((r["strike"] for r in rows), key=pain) if rows else None

    # ATM strike + its IV (avg of CE/PE)
    atm = min(rows, key=lambda r: abs(r["strike"] - spot)) if rows and spot else None
    atm_iv = None
    if atm:
        ivs = [v for v in (atm.get("ce", {}).get("iv"), atm.get("pe", {}).get("iv")) if v]
        atm_iv = sum(ivs) / len(ivs) if ivs else None

    expiries = []
    for e in (data.get("expiryData") or []):
        if isinstance(e, dict):
            expiries.append({"date": e.get("date"), "expiry": e.get("expiry")})

    return {
        "underlying": data.get("symbol"),
        "ltp": spot,
        "expiry": expiry_ts,
        "expiries": expiries,
        "strikes": rows,
        "summary": {
            "pcr_oi": (total_pe_oi / total_ce_oi) if total_ce_oi else None,
            "pcr_volume": (total_pe_vol / total_ce_vol) if total_ce_vol else None,
            "max_pain": max_pain,
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "ce_oi_change": ce_oi_change,
            "pe_oi_change": pe_oi_change,
            "atm_strike": atm["strike"] if atm else None,
            "atm_iv": atm_iv,
        },
    }


def trade_bias(summary: dict[str, Any]) -> dict[str, Any]:
    """Heuristic directional bias from PCR + OI change."""
    pcr = summary.get("pcr_oi") or 0
    ce_chg = summary.get("ce_oi_change") or 0
    pe_chg = summary.get("pe_oi_change") or 0

    signals: list[str] = []
    score = 0
    if pcr > 1.3:
        score += 1; signals.append("PCR>1.3 (bullish - puts oversold)")
    elif pcr < 0.7:
        score -= 1; signals.append("PCR<0.7 (bearish - calls overbought)")

    if pe_chg > ce_chg * 1.2:
        score += 1; signals.append("Put writers active (support building)")
    elif ce_chg > pe_chg * 1.2:
        score -= 1; signals.append("Call writers active (resistance building)")

    if score >= 2:
        bias = "BULLISH"
    elif score <= -2:
        bias = "BEARISH"
    elif score > 0:
        bias = "MILD_BULLISH"
    elif score < 0:
        bias = "MILD_BEARISH"
    else:
        bias = "NEUTRAL"
    return {"bias": bias, "score": score, "signals": signals}
