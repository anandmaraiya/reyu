"""TV webhook token/parsing + legal registry integrity + template canary.

hook_token gates a money-adjacent surface (paper entries from the open
internet); the legal registry gates LIVE deployment; the template canary
catches spec-schema drift breaking the gallery."""
import pytest

from app.routers.tv_hooks import hook_token, _parse_action
from app.legal import LEGAL_DOCS, PLATFORM_DOCS, LIVE_DOCS, current_version, doc_meta
from app.templates_catalog import TEMPLATES, PERSONAS, list_templates, get_template
from app.strategy.spec import StrategySpec


class TestHookToken:
    def test_deterministic(self):
        assert hook_token("abc") == hook_token("abc")

    def test_differs_per_strategy(self):
        assert hook_token("strategy-a") != hook_token("strategy-b")

    def test_length_and_hex(self):
        tok = hook_token("abc")
        assert len(tok) == 32
        int(tok, 16)                                    # valid hex


class TestParseAction:
    @pytest.mark.parametrize("body,expected", [
        (b'{"action": "buy"}', "BUY"),
        (b'{"action": "BUY"}', "BUY"),
        (b'{"signal": "long"}', "BUY"),
        (b'{"action": "exit"}', "EXIT"),
        (b'{"action": "sell"}', "EXIT"),
        (b"buy NIFTY now", "BUY"),
        (b"exit", "EXIT"),
        (b"close position", "EXIT"),
        (b"hello world", None),
        (b"", None),
        (b"\xff\xfe garbage bytes buy", "BUY"),        # tolerant decoding
    ])
    def test_parse(self, body, expected):
        assert _parse_action(body) == expected


class TestLegalRegistry:
    def test_gating_groups_reference_real_docs(self):
        for dt in PLATFORM_DOCS + LIVE_DOCS:
            assert dt in LEGAL_DOCS, f"gating group references unknown doc {dt}"

    def test_exec_auth_is_live_gated_not_platform(self):
        assert "execution_authorization" in LIVE_DOCS
        assert "execution_authorization" not in PLATFORM_DOCS

    def test_versions_positive_ints(self):
        for dt in LEGAL_DOCS:
            assert isinstance(current_version(dt), int)
            assert current_version(dt) >= 1

    def test_doc_meta_never_leaks_body(self):
        for dt in LEGAL_DOCS:
            assert "body" not in doc_meta(dt)

    def test_unknown_doc_raises(self):
        with pytest.raises(KeyError):
            current_version("nonexistent_doc")


class TestTemplateCanary:
    def test_every_template_validates(self):
        """Schema-drift canary: if StrategySpec evolves incompatibly, this
        fails before a user hits a broken copy button."""
        for t in TEMPLATES:
            StrategySpec.model_validate(t["spec"])

    def test_every_template_has_known_persona(self):
        for t in TEMPLATES:
            assert t["persona"] in PERSONAS

    def test_list_filter_and_get(self):
        swing = list_templates("swing_equity")
        assert swing and all(t["persona"] == "swing_equity" for t in swing)
        assert get_template(TEMPLATES[0]["id"]) is not None
        assert get_template("nope") is None

    def test_templates_make_no_profit_claims(self):
        """Compliance: template copy must never claim profitability."""
        banned = ("guaranteed", "profit assured", "sure profit",
                  "best strategy", "top performing", "returns of")
        for t in TEMPLATES:
            text = (t["name"] + " " + t["description"]).lower()
            for phrase in banned:
                assert phrase not in text, f"{t['id']} contains {phrase!r}"
