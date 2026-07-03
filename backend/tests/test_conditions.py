"""Condition evaluator — the gate between market data and money. Both the
positional (options) and dict (equity) variants, every operator."""
import pytest

from app.strategy.conditions import evaluate_one_dict
from app.strategy.spec import Condition


def c(feature: str, op: str, value):
    return Condition(feature=feature, op=op, value=value)


class TestDictOps:
    FEATS = {"eq_rsi_14": 45.0, "eq_close": 1500.0}

    @pytest.mark.parametrize("op,value,expected", [
        (">", 40, True), (">", 45, False),
        ("<", 50, True), ("<", 45, False),
        (">=", 45, True), (">=", 46, False),
        ("<=", 45, True), ("<=", 44, False),
        ("==", 45, True), ("==", 44, False),
    ])
    def test_scalar_ops(self, op, value, expected):
        assert evaluate_one_dict(c("eq_rsi_14", op, value), self.FEATS) is expected

    def test_between_inclusive(self):
        assert evaluate_one_dict(c("eq_rsi_14", "between", [45, 70]), self.FEATS)
        assert evaluate_one_dict(c("eq_rsi_14", "between", [30, 45]), self.FEATS)
        assert not evaluate_one_dict(c("eq_rsi_14", "between", [50, 70]), self.FEATS)

    def test_missing_feature_fails_closed(self):
        # Insufficient warmup omits features — that must NEVER fire an entry.
        assert not evaluate_one_dict(c("eq_sma200_dist_pct", ">", 0), self.FEATS)


class TestCrosses:
    def test_crosses_above_fires_only_on_transition(self):
        cond = c("eq_rsi_14", "crosses_above", 50)
        below, above = {"eq_rsi_14": 48.0}, {"eq_rsi_14": 52.0}
        assert evaluate_one_dict(cond, above, previous_features=below)
        # already above yesterday — no cross
        assert not evaluate_one_dict(cond, above, previous_features={"eq_rsi_14": 51.0})
        # no previous bar — fail closed
        assert not evaluate_one_dict(cond, above, previous_features=None)

    def test_crosses_below(self):
        cond = c("eq_rsi_14", "crosses_below", 50)
        assert evaluate_one_dict(cond, {"eq_rsi_14": 48.0},
                                 previous_features={"eq_rsi_14": 52.0})
        assert not evaluate_one_dict(cond, {"eq_rsi_14": 48.0},
                                     previous_features={"eq_rsi_14": 49.0})

    def test_crosses_missing_prev_feature_fails_closed(self):
        cond = c("eq_rsi_14", "crosses_above", 50)
        assert not evaluate_one_dict(cond, {"eq_rsi_14": 52.0}, previous_features={})
