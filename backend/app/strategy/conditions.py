"""Condition evaluator — Sprint 1.2.

A strategy's `entry_rules.conditions` is a list of {feature, op, value}
clauses joined by AND. This module evaluates them against a feature
vector (whatever `feature_extractor` produces — by default the same
realized-vol vector the bandit uses).

Schedule (days + time window) is checked separately via `schedule_allows`.

Ops supported:
  >  <  >=  <=  ==                 numeric comparison
  between                          [lo, hi] inclusive
  crosses_above  crosses_below     needs previous-bar value; caller must
                                   provide it via `previous_features`.
"""
from __future__ import annotations

from datetime import datetime, time, timezone, timedelta
from typing import Sequence

from app.rl.features import FEATURE_NAMES
from app.strategy.spec import Condition, EntryRules, Schedule


IST = timezone(timedelta(hours=5, minutes=30))


def _feat_index(name: str) -> int:
    try:
        return FEATURE_NAMES.index(name)
    except ValueError as e:
        raise KeyError(f"feature {name!r} not in FEATURE_NAMES") from e


def evaluate_one(
    cond: Condition,
    features: Sequence[float],
    previous_features: Sequence[float] | None = None,
) -> bool:
    val = features[_feat_index(cond.feature)]
    op = cond.op
    if op == ">":
        return val > cond.value
    if op == "<":
        return val < cond.value
    if op == ">=":
        return val >= cond.value
    if op == "<=":
        return val <= cond.value
    if op == "==":
        return val == cond.value
    if op == "between":
        lo, hi = cond.value
        return lo <= val <= hi
    if op == "crosses_above":
        if previous_features is None:
            return False
        prev = previous_features[_feat_index(cond.feature)]
        return prev <= cond.value < val
    if op == "crosses_below":
        if previous_features is None:
            return False
        prev = previous_features[_feat_index(cond.feature)]
        return prev >= cond.value > val
    raise ValueError(f"unsupported op {op!r}")


def evaluate_all(
    conditions: Sequence[Condition],
    features: Sequence[float],
    previous_features: Sequence[float] | None = None,
) -> bool:
    """AND across all conditions. Empty list returns True."""
    return all(evaluate_one(c, features, previous_features) for c in conditions)


def evaluate_one_dict(
    cond: Condition,
    features: dict[str, float],
    previous_features: dict[str, float] | None = None,
) -> bool:
    """Dict-keyed variant of evaluate_one — used by the EQUITY_EOD runner
    whose eq_* features are name→value dicts, not positional vectors.
    A feature missing from `features` (insufficient warmup) fails the
    condition rather than raising."""
    if cond.feature not in features:
        return False
    val = features[cond.feature]
    op = cond.op
    if op == ">":
        return val > cond.value
    if op == "<":
        return val < cond.value
    if op == ">=":
        return val >= cond.value
    if op == "<=":
        return val <= cond.value
    if op == "==":
        return val == cond.value
    if op == "between":
        lo, hi = cond.value
        return lo <= val <= hi
    if op == "crosses_above":
        if not previous_features or cond.feature not in previous_features:
            return False
        return previous_features[cond.feature] <= cond.value < val
    if op == "crosses_below":
        if not previous_features or cond.feature not in previous_features:
            return False
        return previous_features[cond.feature] >= cond.value > val
    raise ValueError(f"unsupported op {op!r}")


# ── Schedule ───────────────────────────────────────────────────────
_DAY_MAP = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4}


def _parse_window(window: str) -> tuple[time, time]:
    a, _, b = window.partition("-")
    return _ist_time(a), _ist_time(b)


def _ist_time(s: str) -> time:
    h, _, m = s.partition(":")
    return time(int(h), int(m))


def schedule_allows(schedule: Schedule, ts_utc: datetime) -> bool:
    """True iff `ts_utc` falls inside the IST schedule (day + window)."""
    ist = ts_utc.replace(tzinfo=timezone.utc).astimezone(IST) if ts_utc.tzinfo is None else ts_utc.astimezone(IST)
    if _day_code(ist.weekday()) not in schedule.days:
        return False
    a, b = _parse_window(schedule.time_window)
    t = ist.time()
    return a <= t <= b


def _day_code(weekday: int) -> str:
    return {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI"}.get(weekday, "SAT")


# ── Entry decision facade ──────────────────────────────────────────
def entry_allowed(
    entry_rules: EntryRules,
    features: Sequence[float],
    ts_utc: datetime,
    previous_features: Sequence[float] | None = None,
) -> tuple[bool, str]:
    """Single call: returns (allowed, reason).

    `reason` is human-readable so the run log can record why each bar
    fired or didn't. Examples: 'OK', 'schedule', 'cond:pcr_oi<1.2'.
    """
    if entry_rules.trigger == "MANUAL":
        return False, "manual-only"
    if not schedule_allows(entry_rules.schedule, ts_utc):
        return False, "schedule"
    if entry_rules.trigger == "SCHEDULE":
        return True, "OK"
    # SIGNAL or BANDIT — check conditions (BANDIT runs additional decider
    # downstream; condition gate is a pre-filter)
    for c in entry_rules.conditions:
        if not evaluate_one(c, features, previous_features):
            return False, f"cond:{c.feature}{c.op}{c.value}"
    return True, "OK"
