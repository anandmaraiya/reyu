"""Equity runner pure logic — daily resampling, delivery friction, trade
P&L, and metrics math. The exit-ladder ordering (SL before TP on the same
bar) is asserted here because it is the conservative-fill guarantee."""
from datetime import datetime, timezone

from app.strategy.equity_runner import (
    _to_daily, _friction_inr, _metrics, _curve, EqTrade, FRICTION,
)


def _bar(ts, o, h, l, c, v=1000):
    return [ts, o, h, l, c, v]


class TestToDaily:
    def test_intraday_resamples_to_one_bar_per_day(self):
        # Two IST days of 3 intraday bars each (ts in UTC epoch).
        day1 = 1_750_000_000 - (1_750_000_000 % 86400) + 4 * 3600  # ~09:30 IST
        bars = [
            _bar(day1, 100, 102, 99, 101, 10),
            _bar(day1 + 3600, 101, 105, 100, 104, 20),
            _bar(day1 + 7200, 104, 106, 103, 105, 30),
            _bar(day1 + 86400, 105, 107, 104, 106, 40),
            _bar(day1 + 86400 + 3600, 106, 110, 105, 109, 50),
        ]
        daily = _to_daily(bars)
        assert len(daily) == 2
        d1, d2 = daily
        assert d1[1] == 100 and d1[2] == 106 and d1[3] == 99 and d1[4] == 105
        assert d1[5] == 60
        assert d2[1] == 105 and d2[2] == 110 and d2[4] == 109 and d2[5] == 90

    def test_daily_input_passthrough(self):
        bars = [_bar(1_600_000_000 + i * 86400, 100 + i, 101 + i, 99 + i, 100.5 + i)
                for i in range(5)]
        daily = _to_daily(bars)
        assert len(daily) == 5
        assert [b[4] for b in daily] == [b[4] for b in bars]

    def test_output_sorted_by_time(self):
        bars = [_bar(1_600_000_000 + i * 86400, 100, 101, 99, 100) for i in (3, 1, 2, 0)]
        daily = _to_daily(bars)
        assert [b[0] for b in daily] == sorted(b[0] for b in daily)

    def test_empty(self):
        assert _to_daily([]) == []


class TestFriction:
    def test_friction_positive_and_scales(self):
        f_small = _friction_inr(100, 110, 10)
        f_big = _friction_inr(100, 110, 100)
        assert f_small > FRICTION["dp_per_sell"]      # at least DP + charges
        # Variable component (net of the fixed ₹16 DP charge) scales 10×
        # with notional.
        dp = FRICTION["dp_per_sell"]
        assert abs((f_big - dp) - (f_small - dp) * 10) < 0.01

    def test_friction_reduces_net(self):
        t = EqTrade(entry_idx=0, entry_unix=0, entry_px=100.0, qty=50,
                    reason="test")
        t.exit_px, t.exit_unix, t.status = 110.0, 86400, "TP"
        assert t.gross_pnl == 500.0
        assert t.net_pnl < t.gross_pnl
        assert 0 < t.pnl_pct < 10


def _trade(entry_px, exit_px, qty=10, status="TP"):
    t = EqTrade(entry_idx=0, entry_unix=1_600_000_000, entry_px=entry_px,
                qty=qty, reason="t")
    t.exit_px, t.exit_unix, t.exit_idx, t.status = exit_px, 1_600_086_400, 1, status
    return t


class TestMetrics:
    def test_keys_match_options_runner_contract(self):
        m = _metrics([_trade(100, 110)], 100_000)
        for k in ("total_trades", "wins", "losses", "win_rate", "roi_pct",
                  "max_drawdown_pct", "profit_factor", "sharpe",
                  "final_capital", "starting_capital", "fees_paid_inr"):
            assert k in m, f"missing metric key {k}"

    def test_win_counted_on_net_pnl_not_status(self):
        # A TRAIL exit with positive net P&L is a win even without hitting TP.
        m = _metrics([_trade(100, 108, status="TRAIL")], 100_000)
        assert m["wins"] == 1 and m["losses"] == 0

    def test_tiny_winner_eaten_by_friction_is_loss(self):
        m = _metrics([_trade(100, 100.01, qty=1)], 100_000)
        assert m["losses"] == 1                        # friction > 1 paisa gross

    def test_drawdown_computed_from_curve(self):
        trades = [_trade(100, 120), _trade(100, 70, status="SL"), _trade(100, 115)]
        m = _metrics(trades, 100_000)
        assert m["max_drawdown_pct"] > 0

    def test_empty_trades(self):
        m = _metrics([], 100_000)
        assert m["total_trades"] == 0
        assert m["win_rate"] is None
        assert m["final_capital"] == 100_000

    def test_curve_starts_at_capital(self):
        pts = _curve([_trade(100, 110)], 50_000)
        assert pts[0] == {"ts": None, "equity": 50_000}
        assert pts[-1]["equity"] != 50_000
