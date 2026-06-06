"""Feature extraction for the RL/bandit trader.

A state vector is built from (a) the live normalised chain, (b) the last
~30 minutes of option_snapshot rows for that underlying, and (c) the
previous trading session's closing snapshot.

The 18-dim vector below is deliberately small so per-underlying linear
policies converge fast. Re-engineer features here without touching the
learner — only `FEATURE_NAMES` and the `extract()` body need editing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import math
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import OptionSnapshot
from app.analytics.chain import normalize_chain
from app.fyers import client as fy

IST = timezone(timedelta(hours=5, minutes=30))

FEATURE_NAMES = [
    "spot_change_today_pct",       # vs prev-day close
    "spot_change_5m_pct",
    "spot_change_30m_pct",
    "pcr_oi",
    "pcr_oi_change_5m",
    "pcr_oi_change_30m",
    "pcr_oi_vs_prev_close",
    "ce_oi_delta_5m_norm",         # CE ΔOI scaled by yesterday's avg
    "pe_oi_delta_5m_norm",
    "ce_pe_oi_imbalance",          # (PE - CE) / (PE + CE)
    "atm_iv",
    "atm_iv_change_30m",
    "iv_skew_put_minus_call",
    "max_pain_distance_pct",       # (spot - max_pain) / spot
    "max_pain_drift_today",        # max_pain_now - max_pain_open
    "session_progress",            # 0 at 09:15, 1 at 15:30
    "bias_score_norm",             # -3..+3 → -1..+1
    "snapshots_count_today",       # data-quality proxy
]
FEATURE_DIM = len(FEATURE_NAMES)


def _ist_session_progress(ts: datetime) -> float:
    """0 at 09:15 IST, 1 at 15:30. Saturates outside trading hours."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ist = ts.astimezone(IST)
    secs_into = (ist.hour * 60 + ist.minute) - (9 * 60 + 15)
    secs_total = (15 * 60 + 30) - (9 * 60 + 15)
    return max(0.0, min(1.0, secs_into / secs_total))


def _safe(x, default=0.0):
    if x is None:
        return default
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return default
        return float(x)
    except Exception:
        return default


async def extract(
    s: AsyncSession,
    underlying: str,
) -> dict[str, Any] | None:
    """Returns {features: [floats], context: {ltp, atm_strike, chain_summary}}
    or None if data is too sparse to act."""

    # 1. Live chain (uses Fyers or mock based on auth state)
    try:
        raw = await fy.option_chain(underlying, 25)
    except Exception:
        return None
    chain = normalize_chain(raw)
    if not chain.get("strikes") or not chain.get("ltp"):
        return None
    summary = chain["summary"]
    spot = chain["ltp"]

    # 2. Recent snapshots — last 30 minutes
    now = datetime.utcnow()
    q_recent = (
        select(OptionSnapshot)
        .where(OptionSnapshot.symbol == underlying, OptionSnapshot.ts >= now - timedelta(minutes=35))
        .order_by(OptionSnapshot.ts)
    )
    recent = (await s.execute(q_recent)).scalars().all()

    snap_now = recent[-1] if recent else None
    snap_5m = next((r for r in reversed(recent) if (now - r.ts).total_seconds() >= 5 * 60), None)
    snap_30m = next((r for r in reversed(recent) if (now - r.ts).total_seconds() >= 30 * 60), None)

    # 3. Today's open snapshot (first row of today's session)
    open_ist = now.replace(tzinfo=timezone.utc).astimezone(IST).replace(hour=9, minute=15, second=0, microsecond=0)
    open_utc = open_ist.astimezone(timezone.utc).replace(tzinfo=None)
    q_open = (
        select(OptionSnapshot)
        .where(OptionSnapshot.symbol == underlying, OptionSnapshot.ts >= open_utc)
        .order_by(OptionSnapshot.ts).limit(1)
    )
    snap_open = (await s.execute(q_open)).scalar_one_or_none()

    # 4. Previous-day close snapshot
    prev_open = open_utc - timedelta(days=1)
    q_prev = (
        select(OptionSnapshot)
        .where(OptionSnapshot.symbol == underlying, OptionSnapshot.ts < open_utc, OptionSnapshot.ts >= prev_open)
        .order_by(OptionSnapshot.ts.desc()).limit(1)
    )
    snap_prev_close = (await s.execute(q_prev)).scalar_one_or_none()

    # ── Feature computation ──────────────────────────────────────
    spot_open = _safe(snap_open.ltp if snap_open else spot, spot)
    spot_5m = _safe(snap_5m.ltp if snap_5m else spot, spot)
    spot_30m = _safe(snap_30m.ltp if snap_30m else spot, spot)
    prev_close = _safe(snap_prev_close.ltp if snap_prev_close else spot, spot)

    pcr_now = _safe(summary.get("pcr_oi"), 1.0)
    pcr_5m = _safe(snap_5m.pcr_oi if snap_5m else pcr_now, pcr_now)
    pcr_30m = _safe(snap_30m.pcr_oi if snap_30m else pcr_now, pcr_now)
    pcr_prev_close = _safe(snap_prev_close.pcr_oi if snap_prev_close else pcr_now, pcr_now)

    ce_oi_5m = _safe(snap_5m.total_ce_oi if snap_5m else 0)
    pe_oi_5m = _safe(snap_5m.total_pe_oi if snap_5m else 0)
    ce_oi_now = _safe(summary.get("total_ce_oi"))
    pe_oi_now = _safe(summary.get("total_pe_oi"))
    ce_oi_yday = _safe(snap_prev_close.total_ce_oi if snap_prev_close else 1, 1)
    pe_oi_yday = _safe(snap_prev_close.total_pe_oi if snap_prev_close else 1, 1)

    atm_iv_now = _safe(summary.get("atm_iv"), 0.2)
    atm_iv_30m = _safe(snap_30m.atm_iv if snap_30m else atm_iv_now, atm_iv_now)

    # IV skew (put IV - call IV) at ±2 strikes — quick approximation
    iv_skew = 0.0
    sorted_strikes = sorted(chain["strikes"], key=lambda r: r["strike"])
    atm = summary.get("atm_strike")
    if atm:
        atm_idx = next((i for i, r in enumerate(sorted_strikes) if r["strike"] == atm), -1)
        if atm_idx >= 2 and atm_idx < len(sorted_strikes) - 2:
            put_iv = _safe((sorted_strikes[atm_idx - 2].get("pe") or {}).get("iv"), 0.0)
            call_iv = _safe((sorted_strikes[atm_idx + 2].get("ce") or {}).get("iv"), 0.0)
            iv_skew = put_iv - call_iv

    max_pain = _safe(summary.get("max_pain"), spot)
    max_pain_open = _safe(snap_open.max_pain if snap_open else max_pain, max_pain)

    bias_score = _safe(snap_now.bias_score if snap_now else 0)

    features = [
        (spot / prev_close - 1.0) * 100 if prev_close else 0.0,
        (spot / spot_5m - 1.0) * 100 if spot_5m else 0.0,
        (spot / spot_30m - 1.0) * 100 if spot_30m else 0.0,
        pcr_now,
        pcr_now - pcr_5m,
        pcr_now - pcr_30m,
        pcr_now - pcr_prev_close,
        (ce_oi_now - ce_oi_5m) / max(ce_oi_yday, 1) * 100,
        (pe_oi_now - pe_oi_5m) / max(pe_oi_yday, 1) * 100,
        (pe_oi_now - ce_oi_now) / max(pe_oi_now + ce_oi_now, 1),
        atm_iv_now,
        atm_iv_now - atm_iv_30m,
        iv_skew,
        (spot - max_pain) / spot * 100 if spot else 0.0,
        (max_pain - max_pain_open) / spot * 100 if spot else 0.0,
        _ist_session_progress(now),
        max(-1.0, min(1.0, bias_score / 3.0)),
        min(1.0, len(recent) / 30.0),
    ]
    assert len(features) == FEATURE_DIM

    return {
        "features": features,
        "context": {
            "ltp": spot, "atm_strike": atm,
            "chain_summary": summary, "snapshots_today": len(recent),
        },
    }
