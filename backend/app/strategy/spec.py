"""Pydantic schema for the strategy spec — the validated JSON shape that
lives in `strategies.spec` and is copied immutably into
`strategy_runs.config_snapshot` at run start.

Design principles:
  * Whitelist all feature names — they must come from `rl.features.FEATURE_NAMES`
    so the same condition vocabulary drives the bandit and user strategies.
  * Universe is single-symbol (per locked design decision #2). Multi-symbol
    strategies are *separate* strategies sharing a recipe template.
  * Two `kind` values:
      - CONDITIONAL: rule-based entry (entry_rules.conditions) + bracket exit
      - RL_BANDIT:   delegates entry to a referenced `rl_policy`; exit
                     bracket still applies. Reserved for Algo tier.
"""
from __future__ import annotations

from datetime import time
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

from app.rl.features import FEATURE_NAMES
from app.strategy.equity_features import EQUITY_FEATURE_NAMES

# Combined condition vocabulary. Options-chain features drive
# CONDITIONAL/RL_BANDIT strategies; eq_* daily-bar features drive
# EQUITY_EOD strategies. The whitelist is the union — kind consistency
# (equity kind ⇒ equity features) is checked in StrategySpec.
ALL_FEATURE_NAMES: list[str] = list(FEATURE_NAMES) + list(EQUITY_FEATURE_NAMES)


# ── Enumerations ───────────────────────────────────────────────────
# EQUITY_EOD: daily-bar cash-equity strategy. Conditions evaluate on
# each day's close (eq_* features); entry fills at next day's open;
# positions are delivery (CNC) and can be held multi-day — exits via
# TP/SL brackets, trailing stop, time stop (days), or end of run.
StrategyKind = Literal["CONDITIONAL", "RL_BANDIT", "EQUITY_EOD"]
StrategyStatus = Literal["DRAFT", "BACKTESTED", "PAPER_LIVE", "LIVE", "ARCHIVED"]
LegAction = Literal["BUY", "SELL"]
InstrumentType = Literal["OPTION", "FUTURE", "EQUITY"]
OptionType = Literal["CE", "PE"]
StrikeMode = Literal["ATM_OFFSET", "ABSOLUTE", "DELTA"]
ExpiryMode = Literal["WEEKLY", "MONTHLY", "ABSOLUTE"]
TriggerType = Literal["SIGNAL", "SCHEDULE", "MANUAL", "BANDIT"]
ConditionOp = Literal[">", "<", ">=", "<=", "==", "between", "crosses_above", "crosses_below"]
DayOfWeek = Literal["MON", "TUE", "WED", "THU", "FRI"]
Tier = Literal["free", "pro", "algo"]


# ── Leg ────────────────────────────────────────────────────────────
class StrikeSpec(BaseModel):
    mode: StrikeMode
    offset: int | None = 0          # ATM_OFFSET: ±N strikes from ATM
    value: float | None = None      # ABSOLUTE: explicit strike
    delta: float | None = None      # DELTA: 0.30, 0.50, etc.

    @model_validator(mode="after")
    def _check(self):
        if self.mode == "ATM_OFFSET" and self.offset is None:
            raise ValueError("ATM_OFFSET requires `offset`")
        if self.mode == "ABSOLUTE" and self.value is None:
            raise ValueError("ABSOLUTE requires `value`")
        if self.mode == "DELTA" and self.delta is None:
            raise ValueError("DELTA requires `delta` (0..1)")
        return self


class ExpirySpec(BaseModel):
    mode: ExpiryMode
    offset: int | None = 0          # WEEKLY: 0=current, 1=next; MONTHLY same
    value: str | None = None        # ABSOLUTE: "2026-06-26"


class Leg(BaseModel):
    leg_id: str = Field(..., description="Stable id within the strategy")
    action: LegAction
    instrument_type: InstrumentType
    option_type: OptionType | None = None
    strike: StrikeSpec | None = None
    expiry: ExpirySpec | None = None
    qty_lots: int = Field(1, ge=1, le=100)
    # Broker product type. EQUITY legs in EQUITY_EOD strategies default
    # to CNC (delivery) so positions can be held overnight; derivatives
    # legs stay INTRADAY unless explicitly set.
    product: Literal["CNC", "INTRADAY", "MARGIN"] | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.instrument_type == "OPTION":
            if not self.option_type:
                raise ValueError("OPTION leg requires option_type (CE|PE)")
            if not self.strike or not self.expiry:
                raise ValueError("OPTION leg requires strike + expiry")
        return self


# ── Entry / exit rules ─────────────────────────────────────────────
class Condition(BaseModel):
    feature: str
    op: ConditionOp
    value: float | list[float]      # list for `between`

    @field_validator("feature")
    @classmethod
    def _whitelist(cls, v):
        if v not in ALL_FEATURE_NAMES:
            allowed = ", ".join(FEATURE_NAMES[:4]) + "… / " + ", ".join(EQUITY_FEATURE_NAMES[:4]) + "…"
            raise ValueError(f"unknown feature `{v}`. Allowed: {allowed}")
        return v

    @model_validator(mode="after")
    def _between_needs_two(self):
        if self.op == "between":
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("`between` requires value=[lo, hi]")
        elif isinstance(self.value, list):
            raise ValueError(f"op `{self.op}` takes scalar value, not list")
        return self


class Schedule(BaseModel):
    days: list[DayOfWeek] = ["MON", "TUE", "WED", "THU", "FRI"]
    time_window: str = "09:15-15:30"  # "HH:MM-HH:MM" IST

    @field_validator("time_window")
    @classmethod
    def _hhmm_range(cls, v):
        a, _, b = v.partition("-")
        for s in (a, b):
            h, _, m = s.partition(":")
            if not (h.isdigit() and m.isdigit()):
                raise ValueError(f"time_window {v!r} not 'HH:MM-HH:MM'")
        return v


class EntryRules(BaseModel):
    trigger: TriggerType
    schedule: Schedule = Field(default_factory=Schedule)
    conditions: list[Condition] = []
    # Approve-from-phone (task #75): when True, paper-live entries wait
    # for the owner's Telegram Approve/Skip instead of firing
    # automatically. No Telegram linked → falls back to auto-entry.
    # Backtests ignore this (historical simulation can't ask).
    require_approval: bool = False

    @model_validator(mode="after")
    def _conditional_needs_conditions(self):
        if self.trigger == "SIGNAL" and not self.conditions:
            raise ValueError("SIGNAL trigger requires at least one condition")
        return self


class ExitRules(BaseModel):
    tp_pct: float = Field(..., gt=0, lt=2)
    sl_pct: float = Field(..., gt=0, lt=2)
    time_stop_minutes: int | None = Field(None, ge=1, le=1440)
    exit_at_close: bool = True
    # Multi-day holds (EQUITY_EOD; ignored by intraday kinds).
    # `exit_at_close` is meaningless for delivery positions — the equity
    # runner ignores it and relies on the fields below + brackets.
    time_stop_days: int | None = Field(None, ge=1, le=365)
    trailing_sl_pct: float | None = Field(None, gt=0, lt=1,
        description="Exit when close drops this fraction below the highest close since entry")


# ── Risk caps ──────────────────────────────────────────────────────
class RiskCaps(BaseModel):
    # le=60 accommodates EQUITY_EOD systematic accumulation (e.g. weekly
    # SIP tranches held ~1 year). Intraday kinds typically use 1-5.
    max_concurrent: int = Field(1, ge=1, le=60)
    max_daily_loss_inr: float = Field(5000, ge=0)
    max_position_inr: float = Field(50_000, ge=0)
    max_drawdown_pct: float = Field(15.0, ge=0, le=100)


# ── RL bandit linkage (kind=RL_BANDIT only) ───────────────────────
class BanditConfig(BaseModel):
    underlying: str                 # must match a row in rl_policy
    min_conviction: float = Field(0.05, ge=0, le=0.9)
    epsilon_override: float | None = None


# ── Root spec ──────────────────────────────────────────────────────
class StrategySpec(BaseModel):
    """Validated payload that lives in `strategies.spec`."""
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    kind: StrategyKind = "CONDITIONAL"
    tier_required: Tier = "free"

    universe: list[str] = Field(..., min_length=1, max_length=1,
        description="Single-symbol per locked design decision #2")
    legs: list[Leg] = Field(..., min_length=1, max_length=4)
    entry_rules: EntryRules
    exit_rules: ExitRules
    risk: RiskCaps = Field(default_factory=RiskCaps)
    tags: list[str] = []
    bandit: BanditConfig | None = None      # required if kind=RL_BANDIT

    @model_validator(mode="after")
    def _kind_consistency(self):
        if self.kind == "RL_BANDIT":
            if not self.bandit:
                raise ValueError("RL_BANDIT strategy requires `bandit` config")
            if self.bandit.underlying != self.universe[0]:
                raise ValueError("bandit.underlying must match universe[0]")
            if self.tier_required == "free":
                raise ValueError("RL_BANDIT strategies need at least `pro` tier")
        # Universe sanity
        u = self.universe[0]
        if ":" not in u:
            raise ValueError("universe symbols must be Fyers-formatted, e.g. NSE:NIFTY50-INDEX")

        if self.kind == "EQUITY_EOD":
            if u.endswith("-INDEX"):
                raise ValueError("EQUITY_EOD needs a tradable stock (e.g. NSE:RELIANCE-EQ), not an index")
            for leg in self.legs:
                if leg.instrument_type != "EQUITY":
                    raise ValueError("EQUITY_EOD legs must be instrument_type=EQUITY")
                if leg.action != "BUY":
                    raise ValueError("EQUITY_EOD supports long (BUY) delivery only — "
                                     "short-selling delivery isn't possible on NSE")
                if leg.product is None:
                    leg.product = "CNC"
            # eq_* features only — chain features don't exist on daily equity bars
            for c in self.entry_rules.conditions:
                if not c.feature.startswith("eq_"):
                    raise ValueError(
                        f"EQUITY_EOD conditions must use eq_* features, got `{c.feature}`")
            if self.entry_rules.trigger == "BANDIT":
                raise ValueError("EQUITY_EOD doesn't support BANDIT trigger")
        else:
            # Options/chain kinds must not use equity daily-bar features.
            for c in self.entry_rules.conditions:
                if c.feature.startswith("eq_"):
                    raise ValueError(
                        f"eq_* features require kind=EQUITY_EOD, got `{c.feature}` on {self.kind}")
        return self


# ── Tier caps ──────────────────────────────────────────────────────
TIER_CAPS: dict[str, dict[str, int]] = {
    "free": {"max_strategies": 3,   "backtests_per_day": 999},
    "pro":  {"max_strategies": 20,  "backtests_per_day": 999},
    "algo": {"max_strategies": 999, "backtests_per_day": 999},
}
# (User locked: no per-day backtest cap. Kept as field for future kill-switch.)
