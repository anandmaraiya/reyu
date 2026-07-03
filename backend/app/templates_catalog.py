"""Curated strategy templates by trading persona (P2a).

Ready-to-copy StrategySpec dicts so a new user lands on something that
matches how they actually trade, instead of a blank spec form. Copying a
template creates a DRAFT the user owns — they backtest, tweak, and
promote it themselves.

Compliance: templates are starting-point structures, not recommendations.
Descriptions explain the mechanic; they never claim profitability.

Personas:
  intraday_options   — expiry-day / short-term options traders
  options_income     — systematic premium sellers
  swing_equity       — multi-day/week stock traders
  systematic_invest  — long-term accumulation (SIP-style)
"""
from __future__ import annotations

from typing import Any

PERSONAS = {
    "intraday_options": {
        "label": "Intraday Options",
        "blurb": "Short-term options structures driven by chain signals (PCR, OI, IV).",
    },
    "options_income": {
        "label": "Options Income",
        "blurb": "Premium-selling structures that aim to collect theta with defined exits.",
    },
    "swing_equity": {
        "label": "Swing Equity",
        "blurb": "Multi-day stock positions from daily-bar signals — trend, momentum, mean-reversion.",
    },
    "systematic_invest": {
        "label": "Systematic Investing",
        "blurb": "Rule-based accumulation on a schedule. Slow, boring, automated.",
    },
}


def _t(id_: str, persona: str, name: str, description: str,
       spec: dict[str, Any]) -> dict[str, Any]:
    spec = {"name": name, "description": description, **spec}
    return {"id": id_, "persona": persona, "name": name,
            "description": description, "spec": spec}


TEMPLATES: list[dict[str, Any]] = [
    # ── Intraday options ────────────────────────────────────────────
    _t("pcr-momentum-ce", "intraday_options",
       "PCR momentum long call",
       "Buys an ATM call when put writing dominates (PCR > 1.2) with a tight "
       "intraday bracket. Squares off by close.",
       {
           "kind": "CONDITIONAL", "tier_required": "free",
           "universe": ["NSE:NIFTY50-INDEX"],
           "legs": [{"leg_id": "L1", "action": "BUY", "instrument_type": "OPTION",
                     "option_type": "CE",
                     "strike": {"mode": "ATM_OFFSET", "offset": 0},
                     "expiry": {"mode": "WEEKLY", "offset": 0}, "qty_lots": 1}],
           "entry_rules": {"trigger": "SIGNAL",
                           "schedule": {"days": ["MON", "TUE", "WED", "THU", "FRI"],
                                        "time_window": "09:30-14:30"},
                           "conditions": [{"feature": "pcr_oi", "op": ">", "value": 1.2}]},
           "exit_rules": {"tp_pct": 0.25, "sl_pct": 0.15, "exit_at_close": True},
           "risk": {"max_concurrent": 1, "max_daily_loss_inr": 5000,
                    "max_position_inr": 20000},
           "tags": ["intraday", "options", "pcr"],
       }),
    _t("bear-bias-pe", "intraday_options",
       "Bear-bias long put",
       "Buys an ATM put when call writing dominates (PCR < 0.8). Intraday "
       "bracket, EOD square-off.",
       {
           "kind": "CONDITIONAL", "tier_required": "free",
           "universe": ["NSE:NIFTY50-INDEX"],
           "legs": [{"leg_id": "L1", "action": "BUY", "instrument_type": "OPTION",
                     "option_type": "PE",
                     "strike": {"mode": "ATM_OFFSET", "offset": 0},
                     "expiry": {"mode": "WEEKLY", "offset": 0}, "qty_lots": 1}],
           "entry_rules": {"trigger": "SIGNAL",
                           "schedule": {"days": ["MON", "TUE", "WED", "THU", "FRI"],
                                        "time_window": "09:30-14:30"},
                           "conditions": [{"feature": "pcr_oi", "op": "<", "value": 0.8}]},
           "exit_rules": {"tp_pct": 0.25, "sl_pct": 0.15, "exit_at_close": True},
           "risk": {"max_concurrent": 1, "max_daily_loss_inr": 5000,
                    "max_position_inr": 20000},
           "tags": ["intraday", "options", "pcr"],
       }),

    # ── Options income ──────────────────────────────────────────────
    _t("iv-spike-strangle-sell", "options_income",
       "High-IV short window",
       "Sells an ATM call when ATM IV is elevated (mean-reversion of IV). "
       "Defined bracket keeps the short risk bounded intraday.",
       {
           "kind": "CONDITIONAL", "tier_required": "free",
           "universe": ["NSE:NIFTY50-INDEX"],
           "legs": [{"leg_id": "L1", "action": "SELL", "instrument_type": "OPTION",
                     "option_type": "CE",
                     "strike": {"mode": "ATM_OFFSET", "offset": 2},
                     "expiry": {"mode": "WEEKLY", "offset": 0}, "qty_lots": 1}],
           "entry_rules": {"trigger": "SIGNAL",
                           "schedule": {"days": ["MON", "TUE", "WED", "THU", "FRI"],
                                        "time_window": "09:45-14:00"},
                           "conditions": [{"feature": "atm_iv", "op": ">", "value": 18}]},
           "exit_rules": {"tp_pct": 0.30, "sl_pct": 0.20, "exit_at_close": True},
           "risk": {"max_concurrent": 1, "max_daily_loss_inr": 8000,
                    "max_position_inr": 60000},
           "tags": ["income", "options", "iv"],
       }),

    # ── Swing equity ────────────────────────────────────────────────
    _t("trend-follow-200", "swing_equity",
       "Trend-following above 200-SMA",
       "Enters a stock in a long-term uptrend (above 200-SMA) with healthy "
       "momentum (RSI 50-70), rides it with a trailing stop, exits after "
       "60 days regardless.",
       {
           "kind": "EQUITY_EOD", "tier_required": "free",
           "universe": ["NSE:RELIANCE-EQ"],
           "legs": [{"leg_id": "L1", "action": "BUY",
                     "instrument_type": "EQUITY", "qty_lots": 1}],
           "entry_rules": {"trigger": "SIGNAL",
                           "conditions": [
                               {"feature": "eq_close_above_sma200", "op": "==", "value": 1},
                               {"feature": "eq_rsi_14", "op": "between", "value": [50, 70]}]},
           "exit_rules": {"tp_pct": 0.20, "sl_pct": 0.07,
                          "trailing_sl_pct": 0.08, "time_stop_days": 60},
           "risk": {"max_concurrent": 1, "max_daily_loss_inr": 10000,
                    "max_position_inr": 100000},
           "tags": ["swing", "equity", "trend"],
       }),
    _t("rsi-dip-buyer", "swing_equity",
       "Oversold dip buyer",
       "Buys a quality stock when RSI drops below 30 while still above its "
       "200-SMA (pullback in an uptrend, not a collapse). 30-day time stop.",
       {
           "kind": "EQUITY_EOD", "tier_required": "free",
           "universe": ["NSE:HDFCBANK-EQ"],
           "legs": [{"leg_id": "L1", "action": "BUY",
                     "instrument_type": "EQUITY", "qty_lots": 1}],
           "entry_rules": {"trigger": "SIGNAL",
                           "conditions": [
                               {"feature": "eq_rsi_14", "op": "<", "value": 30},
                               {"feature": "eq_close_above_sma200", "op": "==", "value": 1}]},
           "exit_rules": {"tp_pct": 0.12, "sl_pct": 0.06, "time_stop_days": 30},
           "risk": {"max_concurrent": 2, "max_daily_loss_inr": 10000,
                    "max_position_inr": 50000},
           "tags": ["swing", "equity", "mean-reversion"],
       }),
    _t("breakout-20d", "swing_equity",
       "20-day breakout",
       "Enters on a close at/near the 20-day high with a volume surge — "
       "classic momentum breakout with a trailing stop.",
       {
           "kind": "EQUITY_EOD", "tier_required": "free",
           "universe": ["NSE:TCS-EQ"],
           "legs": [{"leg_id": "L1", "action": "BUY",
                     "instrument_type": "EQUITY", "qty_lots": 1}],
           "entry_rules": {"trigger": "SIGNAL",
                           "conditions": [
                               {"feature": "eq_high_20d_dist_pct", "op": ">", "value": -0.5},
                               {"feature": "eq_volume_surge", "op": ">", "value": 1.5}]},
           "exit_rules": {"tp_pct": 0.15, "sl_pct": 0.05,
                          "trailing_sl_pct": 0.07, "time_stop_days": 45},
           "risk": {"max_concurrent": 1, "max_daily_loss_inr": 10000,
                    "max_position_inr": 75000},
           "tags": ["swing", "equity", "breakout"],
       }),

    # ── Systematic investing ────────────────────────────────────────
    _t("weekly-sip", "systematic_invest",
       "Weekly accumulation",
       "Buys a fixed rupee amount every Monday, no market-timing. Positions "
       "accumulate; each tranche holds up to a year.",
       {
           "kind": "EQUITY_EOD", "tier_required": "free",
           "universe": ["NSE:ITC-EQ"],
           "legs": [{"leg_id": "L1", "action": "BUY",
                     "instrument_type": "EQUITY", "qty_lots": 1}],
           "entry_rules": {"trigger": "SCHEDULE",
                           "schedule": {"days": ["MON"],
                                        "time_window": "09:15-15:30"}},
           "exit_rules": {"tp_pct": 0.99, "sl_pct": 0.5, "time_stop_days": 365},
           "risk": {"max_concurrent": 52, "max_daily_loss_inr": 100000,
                    "max_position_inr": 5000},
           "tags": ["sip", "equity", "systematic"],
       }),
    _t("dip-sip", "systematic_invest",
       "Buy-the-dip accumulation",
       "Accumulates only on meaningful pullbacks: buys when the stock is "
       "5%+ below its 20-day high but still above the 200-SMA.",
       {
           "kind": "EQUITY_EOD", "tier_required": "free",
           "universe": ["NSE:INFY-EQ"],
           "legs": [{"leg_id": "L1", "action": "BUY",
                     "instrument_type": "EQUITY", "qty_lots": 1}],
           "entry_rules": {"trigger": "SIGNAL",
                           "conditions": [
                               {"feature": "eq_high_20d_dist_pct", "op": "<", "value": -5},
                               {"feature": "eq_close_above_sma200", "op": "==", "value": 1}]},
           "exit_rules": {"tp_pct": 0.99, "sl_pct": 0.4, "time_stop_days": 365},
           "risk": {"max_concurrent": 24, "max_daily_loss_inr": 100000,
                    "max_position_inr": 10000},
           "tags": ["sip", "equity", "dip"],
       }),
]


def list_templates(persona: str | None = None) -> list[dict]:
    """Templates without the full spec body (list view)."""
    out = []
    for t in TEMPLATES:
        if persona and t["persona"] != persona:
            continue
        out.append({
            "id": t["id"], "persona": t["persona"], "name": t["name"],
            "description": t["description"],
            "kind": t["spec"]["kind"],
            "underlying": t["spec"]["universe"][0],
            "tags": t["spec"].get("tags", []),
        })
    return out


def get_template(template_id: str) -> dict | None:
    return next((t for t in TEMPLATES if t["id"] == template_id), None)
