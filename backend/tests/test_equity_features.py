"""Equity feature computation — correctness AND no-lookahead. A lookahead
bug here silently inflates every backtest on the platform."""
from app.strategy.equity_features import compute_equity_features, EQUITY_FEATURE_NAMES


def make_uptrend(n=300, start=100.0, daily=0.003, vol=1_000_000):
    """Synthetic steady uptrend: [ts, o, h, l, c, v] daily candles."""
    candles, px = [], start
    for i in range(n):
        o = px
        cl = px * (1 + daily)
        h, l = cl * 1.005, o * 0.995
        candles.append([1_600_000_000 + i * 86400, o, h, l, cl, vol])
        px = cl
    return candles


class TestCorrectness:
    def test_uptrend_signals(self):
        f = compute_equity_features(make_uptrend(), 299)
        assert f["eq_close_above_sma200"] == 1.0
        assert f["eq_sma20_above_sma50"] == 1.0
        assert f["eq_rsi_14"] > 70                    # monotone rally → hot RSI
        assert f["eq_sma200_dist_pct"] > f["eq_sma20_dist_pct"] > 0
        assert -1.0 < f["eq_high_52w_dist_pct"] <= 0  # at/near highs
        assert abs(f["eq_ret_1d_pct"] - 0.3) < 0.01

    def test_volume_surge(self):
        candles = make_uptrend()
        candles[-1][5] = 3_000_000                    # 3× the 20d average-ish
        f = compute_equity_features(candles, len(candles) - 1)
        assert f["eq_volume_surge"] > 2.5

    def test_gap_pct(self):
        candles = make_uptrend(50)
        prev_close = candles[-2][4]
        candles[-1][1] = prev_close * 1.02            # +2% gap open
        f = compute_equity_features(candles, 49)
        assert abs(f["eq_gap_pct"] - 2.0) < 0.05

    def test_all_names_are_declared(self):
        f = compute_equity_features(make_uptrend(), 299)
        undeclared = set(f) - set(EQUITY_FEATURE_NAMES)
        assert not undeclared, f"features not in whitelist: {undeclared}"


class TestWarmupAndLookahead:
    def test_insufficient_warmup_omits_not_errors(self):
        f = compute_equity_features(make_uptrend(10), 9)
        assert "eq_sma200_dist_pct" not in f
        assert "eq_sma20_dist_pct" not in f
        assert "eq_close" in f                        # always available

    def test_no_lookahead(self):
        """Feature at day i must be identical whether or not future bars
        exist in the input list."""
        candles = make_uptrend(260)
        idx = 220
        with_future = compute_equity_features(candles, idx)
        without_future = compute_equity_features(candles[: idx + 1], idx)
        assert with_future == without_future

    def test_single_bar(self):
        f = compute_equity_features(make_uptrend(1), 0)
        assert f["eq_close"] > 0
        assert "eq_ret_1d_pct" not in f
