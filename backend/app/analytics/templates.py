"""Pre-built option strategy templates.

Each template is a function (chain, lots=1, width=...) -> list of legs ready
to drop into the Strategy Builder. Strikes are picked relative to ATM using
the chain's actual strike spacing.
"""
from __future__ import annotations
from typing import Any


def _strikes_around_atm(chain: dict[str, Any]) -> tuple[list, float, float]:
    rows = sorted(chain.get("strikes", []), key=lambda r: r["strike"])
    if len(rows) < 5:
        return [], 0, 0
    atm_k = chain["summary"].get("atm_strike") or rows[len(rows) // 2]["strike"]
    spacing = rows[1]["strike"] - rows[0]["strike"]
    return rows, atm_k, spacing


def _leg(row: dict, side: str, action: str, lots: int) -> dict | None:
    leg = row.get(side)
    if not leg or not leg.get("symbol"):
        return None
    return {
        "symbol": leg["symbol"], "action": action, "qty": lots,  # lots; UI will * lot_size
        "price": leg.get("ltp", 0),
        "strike": row["strike"], "option_type": side.upper(),
    }


def _find(rows, k):
    return next((r for r in rows if r["strike"] == k), None)


def bull_call_spread(chain, lots=1, width_steps=2, **_):
    rows, atm, spacing = _strikes_around_atm(chain)
    if not rows: return []
    buy = _find(rows, atm)
    sell = _find(rows, atm + width_steps * spacing)
    return [l for l in [_leg(buy, "ce", "BUY", lots), _leg(sell, "ce", "SELL", lots)] if l]


def bear_put_spread(chain, lots=1, width_steps=2, **_):
    rows, atm, spacing = _strikes_around_atm(chain)
    if not rows: return []
    buy = _find(rows, atm)
    sell = _find(rows, atm - width_steps * spacing)
    return [l for l in [_leg(buy, "pe", "BUY", lots), _leg(sell, "pe", "SELL", lots)] if l]


def long_straddle(chain, lots=1, **_):
    rows, atm, _sp = _strikes_around_atm(chain)
    r = _find(rows, atm)
    return [l for l in [_leg(r, "ce", "BUY", lots), _leg(r, "pe", "BUY", lots)] if l]


def short_straddle(chain, lots=1, **_):
    rows, atm, _sp = _strikes_around_atm(chain)
    r = _find(rows, atm)
    return [l for l in [_leg(r, "ce", "SELL", lots), _leg(r, "pe", "SELL", lots)] if l]


def long_strangle(chain, lots=1, width_steps=2, **_):
    rows, atm, sp = _strikes_around_atm(chain)
    rc = _find(rows, atm + width_steps * sp)
    rp = _find(rows, atm - width_steps * sp)
    return [l for l in [_leg(rc, "ce", "BUY", lots), _leg(rp, "pe", "BUY", lots)] if l]


def iron_condor(chain, lots=1, width_steps=2, wing_steps=2, **_):
    rows, atm, sp = _strikes_around_atm(chain)
    legs = []
    # Short inner CE + Long outer CE
    si = _find(rows, atm + width_steps * sp)
    lo = _find(rows, atm + (width_steps + wing_steps) * sp)
    # Short inner PE + Long outer PE
    sip = _find(rows, atm - width_steps * sp)
    lop = _find(rows, atm - (width_steps + wing_steps) * sp)
    for r, side, action in [(si, "ce", "SELL"), (lo, "ce", "BUY"),
                            (sip, "pe", "SELL"), (lop, "pe", "BUY")]:
        l = _leg(r, side, action, lots) if r else None
        if l: legs.append(l)
    return legs


def iron_butterfly(chain, lots=1, wing_steps=2, **_):
    rows, atm, sp = _strikes_around_atm(chain)
    r_atm = _find(rows, atm)
    r_lc = _find(rows, atm + wing_steps * sp)
    r_lp = _find(rows, atm - wing_steps * sp)
    legs = []
    for r, side, action in [(r_atm, "ce", "SELL"), (r_atm, "pe", "SELL"),
                            (r_lc, "ce", "BUY"), (r_lp, "pe", "BUY")]:
        l = _leg(r, side, action, lots) if r else None
        if l: legs.append(l)
    return legs


def call_butterfly(chain, lots=1, wing_steps=2, **_):
    rows, atm, sp = _strikes_around_atm(chain)
    lower = _find(rows, atm - wing_steps * sp)
    body = _find(rows, atm)
    upper = _find(rows, atm + wing_steps * sp)
    legs = []
    for r, side, action, q in [(lower, "ce", "BUY", lots), (body, "ce", "SELL", 2 * lots),
                                (upper, "ce", "BUY", lots)]:
        l = _leg(r, side, action, q) if r else None
        if l: legs.append(l)
    return legs


TEMPLATES = {
    "BULL_CALL_SPREAD": {"fn": bull_call_spread, "view": "BULLISH",
                          "label": "Bull Call Spread", "desc": "Buy ATM CE, sell OTM CE — capped upside, defined risk"},
    "BEAR_PUT_SPREAD":  {"fn": bear_put_spread,  "view": "BEARISH",
                          "label": "Bear Put Spread",  "desc": "Buy ATM PE, sell OTM PE — capped downside, defined risk"},
    "LONG_STRADDLE":    {"fn": long_straddle,    "view": "VOL_LONG",
                          "label": "Long Straddle",    "desc": "Buy ATM CE + PE — profit on big move either way"},
    "SHORT_STRADDLE":   {"fn": short_straddle,   "view": "VOL_SHORT",
                          "label": "Short Straddle",   "desc": "Sell ATM CE + PE — profit on range-bound; unlimited risk"},
    "LONG_STRANGLE":    {"fn": long_strangle,    "view": "VOL_LONG",
                          "label": "Long Strangle",    "desc": "Buy OTM CE + OTM PE — cheaper than straddle"},
    "IRON_CONDOR":      {"fn": iron_condor,      "view": "NEUTRAL",
                          "label": "Iron Condor",      "desc": "Defined-risk credit spread — profit if price stays between wings"},
    "IRON_BUTTERFLY":   {"fn": iron_butterfly,   "view": "NEUTRAL",
                          "label": "Iron Butterfly",   "desc": "Short ATM straddle hedged with OTM wings"},
    "CALL_BUTTERFLY":   {"fn": call_butterfly,   "view": "NEUTRAL",
                          "label": "Call Butterfly",   "desc": "Long 1 / Short 2 / Long 1 calls — pin-risk at body strike"},
}


def list_templates():
    return [{"key": k, "view": v["view"], "label": v["label"], "desc": v["desc"]}
            for k, v in TEMPLATES.items()]


def apply_template(key: str, chain: dict, lots: int = 1, width_steps: int = 2, wing_steps: int = 2):
    t = TEMPLATES.get(key)
    if not t:
        return []
    return t["fn"](chain, lots=lots, width_steps=width_steps, wing_steps=wing_steps)
