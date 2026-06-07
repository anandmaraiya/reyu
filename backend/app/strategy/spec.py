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


# ── Enumerations ───────────────────────────────────────────────────
StrategyKind = Literal["CONDITIONAL", "RL_BANDIT"]
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
        if v not in FEATURE_NAMES:
            allowed = ", ".join(FEATURE_NAMES[:6]) + "…"
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


# ── Risk caps ──────────────────────────────────────────────────────
class RiskCaps(BaseModel):
    max_concurrent: int = Field(1, ge=1, le=20)
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
        return self


# ── Tier caps ──────────────────────────────────────────────────────
TIER_CAPS: dict[str, dict[str, int]] = {
    "free": {"max_strategies": 3,   "backtests_per_day": 999},
    "pro":  {"max_strategies": 20,  "backtests_per_day": 999},
    "algo": {"max_strategies": 999, "backtests_per_day": 999},
}
# (User locked: no per-day backtest cap. Kept as field for future kill-switch.)
