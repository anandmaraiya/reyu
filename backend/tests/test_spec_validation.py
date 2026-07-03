"""StrategySpec validation — the contract every strategy passes before it
can spend (paper or real) money. Guards here are compliance-critical:
kind/feature consistency, no short delivery, no index equity."""
import pytest
from pydantic import ValidationError

from app.strategy.spec import StrategySpec


def _equity_spec(**over):
    base = {
        "name": "test equity",
        "kind": "EQUITY_EOD",
        "universe": ["NSE:RELIANCE-EQ"],
        "legs": [{"leg_id": "L1", "action": "BUY", "instrument_type": "EQUITY"}],
        "entry_rules": {"trigger": "SIGNAL", "conditions": [
            {"feature": "eq_rsi_14", "op": "<", "value": 30}]},
        "exit_rules": {"tp_pct": 0.1, "sl_pct": 0.05},
    }
    base.update(over)
    return base


def _options_spec(**over):
    base = {
        "name": "test options",
        "kind": "CONDITIONAL",
        "universe": ["NSE:NIFTY50-INDEX"],
        "legs": [{"leg_id": "L1", "action": "BUY", "instrument_type": "OPTION",
                  "option_type": "CE",
                  "strike": {"mode": "ATM_OFFSET", "offset": 0},
                  "expiry": {"mode": "WEEKLY", "offset": 0}}],
        "entry_rules": {"trigger": "SIGNAL", "conditions": [
            {"feature": "pcr_oi", "op": ">", "value": 1.2}]},
        "exit_rules": {"tp_pct": 0.25, "sl_pct": 0.15},
    }
    base.update(over)
    return base


class TestEquityKindGuards:
    def test_valid_equity_spec_passes(self):
        spec = StrategySpec.model_validate(_equity_spec())
        assert spec.kind == "EQUITY_EOD"

    def test_equity_leg_defaults_to_cnc(self):
        spec = StrategySpec.model_validate(_equity_spec())
        assert spec.legs[0].product == "CNC"

    def test_short_delivery_rejected(self):
        # No short-selling delivery on NSE — SELL equity legs must fail.
        with pytest.raises(ValidationError, match="BUY"):
            StrategySpec.model_validate(_equity_spec(
                legs=[{"leg_id": "L1", "action": "SELL",
                       "instrument_type": "EQUITY"}]))

    def test_index_universe_rejected(self):
        with pytest.raises(ValidationError, match="tradable stock"):
            StrategySpec.model_validate(_equity_spec(
                universe=["NSE:NIFTY50-INDEX"]))

    def test_option_leg_on_equity_kind_rejected(self):
        with pytest.raises(ValidationError, match="EQUITY"):
            StrategySpec.model_validate(_equity_spec(
                legs=[{"leg_id": "L1", "action": "BUY",
                       "instrument_type": "OPTION", "option_type": "CE",
                       "strike": {"mode": "ATM_OFFSET", "offset": 0},
                       "expiry": {"mode": "WEEKLY", "offset": 0}}]))

    def test_chain_feature_on_equity_kind_rejected(self):
        with pytest.raises(ValidationError, match="eq_"):
            StrategySpec.model_validate(_equity_spec(
                entry_rules={"trigger": "SIGNAL", "conditions": [
                    {"feature": "pcr_oi", "op": ">", "value": 1.2}]}))

    def test_bandit_trigger_on_equity_rejected(self):
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(_equity_spec(
                entry_rules={"trigger": "BANDIT", "conditions": []}))


class TestOptionsKindGuards:
    def test_valid_conditional_passes(self):
        spec = StrategySpec.model_validate(_options_spec())
        assert spec.kind == "CONDITIONAL"

    def test_eq_feature_on_options_kind_rejected(self):
        with pytest.raises(ValidationError, match="EQUITY_EOD"):
            StrategySpec.model_validate(_options_spec(
                entry_rules={"trigger": "SIGNAL", "conditions": [
                    {"feature": "eq_rsi_14", "op": "<", "value": 30}]}))

    def test_unknown_feature_rejected(self):
        with pytest.raises(ValidationError, match="unknown feature"):
            StrategySpec.model_validate(_options_spec(
                entry_rules={"trigger": "SIGNAL", "conditions": [
                    {"feature": "totally_made_up", "op": ">", "value": 1}]}))

    def test_rl_bandit_requires_config_and_tier(self):
        with pytest.raises(ValidationError, match="bandit"):
            StrategySpec.model_validate(_options_spec(kind="RL_BANDIT"))


class TestExitRules:
    def test_multiday_fields_accepted(self):
        spec = StrategySpec.model_validate(_equity_spec(
            exit_rules={"tp_pct": 0.2, "sl_pct": 0.1,
                        "trailing_sl_pct": 0.08, "time_stop_days": 60}))
        assert spec.exit_rules.trailing_sl_pct == 0.08
        assert spec.exit_rules.time_stop_days == 60

    def test_tp_sl_bounds(self):
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(_equity_spec(
                exit_rules={"tp_pct": 0, "sl_pct": 0.1}))
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(_equity_spec(
                exit_rules={"tp_pct": 0.1, "sl_pct": 2.5}))

    def test_between_needs_two_values(self):
        with pytest.raises(ValidationError, match="between"):
            StrategySpec.model_validate(_equity_spec(
                entry_rules={"trigger": "SIGNAL", "conditions": [
                    {"feature": "eq_rsi_14", "op": "between", "value": 30}]}))


class TestRiskCaps:
    def test_sip_accumulation_max_concurrent(self):
        # Weekly SIP for a year needs up to 52 open tranches.
        spec = StrategySpec.model_validate(_equity_spec(
            entry_rules={"trigger": "SCHEDULE"},
            risk={"max_concurrent": 52, "max_position_inr": 5000}))
        assert spec.risk.max_concurrent == 52

    def test_max_concurrent_upper_bound(self):
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(_equity_spec(
                risk={"max_concurrent": 100}))
