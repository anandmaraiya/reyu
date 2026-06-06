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

from app.db import OptionSnapshot, OptionStrikeSnapshot
from app.analytics.chain import normalize_chain
from app.fyers import client as fy

IST = timezone(timedelta(hours=5, minutes=30))

# ── Feature layout ──────────────────────────────────────────────────
# Dims 0..17 — original "summary" features (chain aggregates + spot).
# Dims 18..29 — new ATM-band / writer-dynamics features encoding the
# hypothesis: PCR / OI redistribution across near-ATM strikes precedes
# spot direction, and equilibrium of writer OI pins LTP. These tap
# `OptionStrikeSnapshot` history when present; gracefully zero out
# when the per-strike table hasn't filled yet (post-deploy, before
# Monday's open).
FEATURE_NAMES = [
    # ── 0..2: spot momentum ──
    "spot_change_today_pct",       # vs prev-day close
    "spot_change_5m_pct",
    "spot_change_30m_pct",
    # ── 3..6: full-chain PCR ──
    "pcr_oi",
    "pcr_oi_change_5m",
    "pcr_oi_change_30m",
    "pcr_oi_vs_prev_close",
    # ── 7..9: aggregate OI dynamics ──
    "ce_oi_delta_5m_norm",         # CE ΔOI scaled by yesterday's avg
    "pe_oi_delta_5m_norm",
    "ce_pe_oi_imbalance",          # (PE - CE) / (PE + CE)
    # ── 10..12: IV ──
    "atm_iv",
    "atm_iv_change_30m",
    "iv_skew_put_minus_call",
    # ── 13..14: max pain ──
    "max_pain_distance_pct",
    "max_pain_drift_today",
    # ── 15..17: session / bias / data quality ──
    "session_progress",
    "bias_score_norm",
    "snapshots_count_today",
    # ── 18..29: ATM-band writer-dynamics (the new hypothesis features) ──
    "pcr_oi_atm_band",             # PCR within ATM±2 strikes only
    "writer_skew_log",             # log(Σce_oi above spot / Σpe_oi below)
    "oi_com_ce_norm",              # CE OI centre-of-mass distance from spot, %
    "oi_com_pe_norm",              # PE OI centre-of-mass distance from spot, %
    "pcr_local_gradient",          # PCR(ATM) - PCR(ATM+2): local skew slope
    "atm_writer_aggression",       # |ce_oi_chg_atm| + |pe_oi_chg_atm|, normed
    "ce_buildup_above_5m",         # Σ ce_oi_chg at K>spot in last 5m, normed
    "pe_buildup_below_5m",         # Σ pe_oi_chg at K<spot in last 5m, normed
    "ce_unwind_above_5m",          # writers covering above spot → bullish breakout
    "pe_unwind_below_5m",          # writers covering below spot → bearish breakdown
    "oi_com_drift_5m",             # change in (com_ce - com_pe) over last 5m
    "oi_velocity_ratio",           # |ΔOI 5m| / |ΔOI 30m|: writer-flow acceleration
]
FEATURE_DIM = len(FEATURE_NAMES)
BAND_FEATURE_START = 18           # backfill / legacy paths can slice features[:BAND_FEATURE_START]


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


# ── ATM-band feature computation ────────────────────────────────────
# Hypothesis: writer behaviour at near-ATM strikes encodes directional
# pressure before it shows in spot. We measure (a) the OI distribution
# *now* across the band, (b) how that distribution is shifting over the
# last 5–30 min via OptionStrikeSnapshot history, and (c) writer
# "aggression" — fresh writes vs unwinds at the strikes that matter.
ATM_BAND_HALF_WIDTH = 5            # ATM ± this many strikes feeds the band features
BAND_ZERO = [0.0] * 12             # safe fallback when chain or history is empty


def _atm_band_now(chain: dict, spot: float, atm: float | None) -> list[float]:
    """Six features computable from the *current* chain only.

    Returns the first half of the band block:
        [pcr_atm_band, writer_skew_log, oi_com_ce_norm, oi_com_pe_norm,
         pcr_local_gradient, atm_writer_aggression]
    """
    if not atm or not spot:
        return [0.0] * 6
    strikes = sorted(chain.get("strikes") or [], key=lambda r: r["strike"])
    if not strikes:
        return [0.0] * 6

    # ATM-band slice
    atm_idx = next((i for i, r in enumerate(strikes) if r["strike"] == atm), -1)
    if atm_idx < 0:
        return [0.0] * 6
    lo = max(0, atm_idx - ATM_BAND_HALF_WIDTH)
    hi = min(len(strikes), atm_idx + ATM_BAND_HALF_WIDTH + 1)
    band = strikes[lo:hi]

    # 1) PCR within ATM-band
    band_ce_oi = sum(_safe((r.get("ce") or {}).get("oi")) for r in band)
    band_pe_oi = sum(_safe((r.get("pe") or {}).get("oi")) for r in band)
    pcr_band = band_pe_oi / band_ce_oi if band_ce_oi else 1.0

    # 2) Writer skew — call OI above spot vs put OI below.
    # Calls are typically written at resistance (above), puts at support (below).
    ce_above = sum(_safe((r.get("ce") or {}).get("oi")) for r in strikes if r["strike"] > spot)
    pe_below = sum(_safe((r.get("pe") or {}).get("oi")) for r in strikes if r["strike"] < spot)
    if ce_above > 0 and pe_below > 0:
        writer_skew_log = math.log(ce_above / pe_below)
    else:
        writer_skew_log = 0.0
    # Clamp to keep policy normalisation stable
    writer_skew_log = max(-3.0, min(3.0, writer_skew_log))

    # 3) & 4) Centre of mass of CE / PE OI, expressed as % distance from spot.
    # com_ce > 0 → CE OI piled above spot (resistance distant), com_pe < 0
    # → PE OI piled below (support distant).
    def _com(side: str) -> float:
        num = 0.0; den = 0.0
        for r in strikes:
            oi = _safe((r.get(side) or {}).get("oi"))
            num += r["strike"] * oi
            den += oi
        if den <= 0:
            return 0.0
        return (num / den - spot) / spot * 100
    com_ce = _com("ce")
    com_pe = _com("pe")

    # 5) PCR local gradient — PCR at ATM minus PCR two strikes up.
    # Positive: puts dominating ATM (writers expect support holds) but calls
    # rising at +2 (resistance forming) → mean-reverting pin.
    def _row_pcr(r):
        ce = _safe((r.get("ce") or {}).get("oi"))
        pe = _safe((r.get("pe") or {}).get("oi"))
        return pe / ce if ce > 0 else 0.0
    pcr_atm = _row_pcr(strikes[atm_idx])
    pcr_plus2 = _row_pcr(strikes[atm_idx + 2]) if atm_idx + 2 < len(strikes) else pcr_atm
    pcr_gradient = pcr_atm - pcr_plus2

    # 6) ATM-writer aggression — |Δoi_atm_ce| + |Δoi_atm_pe| normalised by
    # band OI. High value = active redistribution at the pin strike.
    atm_row = strikes[atm_idx]
    atm_ce_chg = abs(_safe((atm_row.get("ce") or {}).get("oi_change")))
    atm_pe_chg = abs(_safe((atm_row.get("pe") or {}).get("oi_change")))
    band_total = band_ce_oi + band_pe_oi
    atm_aggression = (atm_ce_chg + atm_pe_chg) / band_total if band_total > 0 else 0.0

    return [pcr_band, writer_skew_log, com_ce, com_pe, pcr_gradient, atm_aggression]


def _atm_band_history(
    snaps: list,                # ordered ascending by ts
    spot: float, atm: float | None,
) -> list[float]:
    """Six velocity / drift features from per-strike snapshot history.

    Returns:
        [ce_buildup_above_5m, pe_buildup_below_5m,
         ce_unwind_above_5m, pe_unwind_below_5m,
         oi_com_drift_5m, oi_velocity_ratio]

    All zero when the per-strike table is empty (table is freshly added —
    real values start flowing once the scheduler fills it through a full
    trading day).
    """
    if not snaps or not spot:
        return [0.0] * 6

    now = snaps[-1].ts
    band_lo = (atm or spot) - 1e9  # don't limit by band — we want above/below split

    def _within(seconds: int):
        return [r for r in snaps if (now - r.ts).total_seconds() <= seconds]

    last5 = _within(5 * 60)
    last30 = _within(30 * 60)
    if len(last5) < 2:
        return [0.0] * 6

    def _sum_chg_above(rows, side: str) -> float:
        return sum(getattr(r, f"{side}_oi_change", 0) or 0
                   for r in rows if r.strike > spot)

    def _sum_chg_below(rows, side: str) -> float:
        return sum(getattr(r, f"{side}_oi_change", 0) or 0
                   for r in rows if r.strike < spot)

    total_oi_5 = sum((r.ce_oi or 0) + (r.pe_oi or 0) for r in last5) or 1

    # Buildup (positive ΔOI = fresh writes)
    ce_above_chg = _sum_chg_above(last5, "ce")
    pe_below_chg = _sum_chg_below(last5, "pe")
    ce_buildup_above = max(0.0, ce_above_chg) / total_oi_5 * 100
    pe_buildup_below = max(0.0, pe_below_chg) / total_oi_5 * 100
    # Unwinds (negative ΔOI = writers covering — bullish above, bearish below)
    ce_unwind_above = max(0.0, -ce_above_chg) / total_oi_5 * 100
    pe_unwind_below = max(0.0, -pe_below_chg) / total_oi_5 * 100

    # OI centre-of-mass drift: (com_ce - com_pe) now vs ~5min ago.
    def _com_diff(rows) -> float:
        ce_num = ce_den = pe_num = pe_den = 0.0
        for r in rows:
            ce_num += r.strike * (r.ce_oi or 0); ce_den += (r.ce_oi or 0)
            pe_num += r.strike * (r.pe_oi or 0); pe_den += (r.pe_oi or 0)
        com_ce = ce_num / ce_den if ce_den else 0
        com_pe = pe_num / pe_den if pe_den else 0
        return com_ce - com_pe

    snap_5min_ago = last5[0]
    com_now = _com_diff([r for r in snaps if r.ts == now])
    com_then = _com_diff([r for r in snaps if r.ts == snap_5min_ago.ts])
    com_drift = (com_now - com_then) / spot * 100 if spot else 0.0

    # Velocity ratio: how concentrated is writer flow into the most recent 5m
    # vs the whole 30m window? Higher = accelerating activity.
    def _abs_chg_sum(rows):
        return sum(abs(r.ce_oi_change or 0) + abs(r.pe_oi_change or 0) for r in rows)
    chg_5 = _abs_chg_sum(last5)
    chg_30 = _abs_chg_sum(last30)
    velocity = (chg_5 / chg_30) if chg_30 > 0 else 0.0

    return [ce_buildup_above, pe_buildup_below,
            ce_unwind_above, pe_unwind_below,
            com_drift, velocity]


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

    # 2. Recent snapshots — last 30 minutes (aggregate + per-strike)
    now = datetime.utcnow()
    q_recent = (
        select(OptionSnapshot)
        .where(OptionSnapshot.symbol == underlying, OptionSnapshot.ts >= now - timedelta(minutes=35))
        .order_by(OptionSnapshot.ts)
    )
    recent = (await s.execute(q_recent)).scalars().all()

    # Per-strike snapshots for the new ATM-band features. Will be empty
    # until the scheduler has filled the table through a full session.
    q_strikes = (
        select(OptionStrikeSnapshot)
        .where(OptionStrikeSnapshot.underlying == underlying,
               OptionStrikeSnapshot.ts >= now - timedelta(minutes=35))
        .order_by(OptionStrikeSnapshot.ts)
    )
    strike_snaps = (await s.execute(q_strikes)).scalars().all()

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

    # ── Dims 0..17: legacy summary block ──
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
    # ── Dims 18..29: ATM-band writer-dynamics block ──
    features.extend(_atm_band_now(chain, spot, atm))
    features.extend(_atm_band_history(strike_snaps, spot, atm))
    assert len(features) == FEATURE_DIM, f"expected {FEATURE_DIM} got {len(features)}"

    return {
        "features": features,
        "context": {
            "ltp": spot, "atm_strike": atm,
            "chain_summary": summary, "snapshots_today": len(recent),
        },
    }
