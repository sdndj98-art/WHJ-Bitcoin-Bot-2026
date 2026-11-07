import unittest

from strategy_lab import _market_regime_diagnostics, _wilson_interval


class MarketRegimeDiagnosticsTests(unittest.TestCase):
    def test_bullish_regime_and_strategy_signal_metrics_are_reported(self):
        prices = [100.0 + i * 0.5 for i in range(420)]
        signals = {
            "trend_candidate": [True] * len(prices),
            "inactive_candidate": [False] * len(prices),
        }
        result = _market_regime_diagnostics(prices, signals, 250)
        bullish = result["regimes"]["bullish"]
        self.assertGreater(bullish["bars"], 30)
        self.assertEqual(bullish["evidence_status"], "DESCRIPTIVE_ONLY")
        trend = bullish["strategy_signal_diagnostics"]["trend_candidate"]
        self.assertEqual(trend["active_signal_bars"], bullish["bars"])
        self.assertEqual(trend["evidence_status"], "DESCRIPTIVE_ONLY")
        self.assertIsNotNone(trend["active_forward_return_pct"])
        interval = trend["positive_active_forward_bar_ci95_pct"]
        self.assertEqual(interval["method"], "wilson_95")
        self.assertLessEqual(interval["lower_pct"], trend["positive_active_forward_bar_pct"])
        self.assertGreaterEqual(interval["upper_pct"], trend["positive_active_forward_bar_pct"])
        self.assertIsNotNone(trend["mean_active_forward_bar_return_pct"])
        inactive = bullish["strategy_signal_diagnostics"]["inactive_candidate"]
        self.assertEqual(inactive["active_signal_bars"], 0)
        self.assertEqual(inactive["evidence_status"], "INSUFFICIENT_SAMPLE")
        self.assertIsNone(inactive["active_forward_return_pct"])
        self.assertIsNone(inactive["positive_active_forward_bar_ci95_pct"])
        self.assertIsNone(inactive["mean_active_forward_bar_return_pct"])

    def test_insufficient_regime_sample_is_never_promoted(self):
        prices = [100.0 + i * 0.1 for i in range(250)]
        result = _market_regime_diagnostics(
            prices, {"candidate": [True] * len(prices)}, 220
        )
        for regime in result["regimes"].values():
            if regime["bars"] < 30:
                self.assertEqual(regime["evidence_status"], "INSUFFICIENT_SAMPLE")

    def test_regime_classification_is_explicitly_close_time_and_not_trade_pnl(self):
        prices = [100.0 + i * 0.2 for i in range(350)]
        result = _market_regime_diagnostics(
            prices, {"candidate": [True] * len(prices)}, 220
        )
        self.assertIn("known at the prior close", result["measurement"])
        self.assertIn("not trade-level PnL", result["measurement"])
        self.assertIn("200-SMA", result["classification"])


    def test_wilson_interval_handles_edges_and_invalid_counts(self):
        self.assertIsNone(_wilson_interval(0, 0))
        zero = _wilson_interval(0, 20)
        all_positive = _wilson_interval(20, 20)
        self.assertEqual(zero["lower_pct"], 0.0)
        self.assertLess(zero["upper_pct"], 20.0)
        self.assertGreater(all_positive["lower_pct"], 80.0)
        self.assertEqual(all_positive["upper_pct"], 100.0)
        with self.assertRaises(ValueError):
            _wilson_interval(3, 2)
        with self.assertRaises(ValueError):
            _wilson_interval(True, 2)

if __name__ == "__main__":
    unittest.main()
