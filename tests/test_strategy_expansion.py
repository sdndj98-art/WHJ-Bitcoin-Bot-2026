import unittest

from strategy_lab import _signals, run_strategy_lab


class StrategyExpansionTests(unittest.TestCase):
    def test_new_candidate_signals_are_boolean_and_aligned(self):
        prices = []
        price = 100.0
        for index in range(900):
            drift = 0.0012 if (index // 120) % 2 == 0 else -0.00045
            pulse = 0.003 * ((index % 17) - 8) / 8
            price *= 1.0 + drift + pulse
            prices.append(price)
        signals = _signals(prices)
        candidates = ("ema_pullback_trend", "donchian_20_10_breakout", "macd_trend_confirmation", "rsi_trend_pullback", "volatility_contraction_breakout")
        for name in candidates:
            self.assertIn(name, signals)
            self.assertEqual(len(signals[name]), len(prices))
            self.assertTrue(all(isinstance(value, bool) for value in signals[name]))

    def test_volatility_breakout_is_prefix_causal(self):
        prices = [100.0]
        for index in range(1, 900):
            drift = 0.0005 if index < 600 else 0.001
            pulse = 0.001 * ((index % 11) - 5) / 5
            prices.append(prices[-1] * (1.0 + drift + pulse))
        full = _signals(prices)["volatility_contraction_breakout"]
        prefix = _signals(prices[:700])["volatility_contraction_breakout"]
        self.assertEqual(full[:700], prefix)

    def test_new_candidates_enter_standard_holdout_pipeline(self):
        prices = [100.0]
        for index in range(1, 1200):
            drift = 0.0007 if (index // 160) % 2 == 0 else -0.0002
            prices.append(prices[-1] * (1.0 + drift + 0.001 * ((index % 13) - 6) / 6))
        report = run_strategy_lab(prices)
        for name in ("ema_pullback_trend", "donchian_20_10_breakout", "macd_trend_confirmation", "rsi_trend_pullback", "volatility_contraction_breakout"):
            self.assertIn(name, report["strategies"])
            self.assertEqual(len(report["strategies"][name]["walk_forward_windows"]), 3)
        self.assertIn("candidate_strategy_rules", report)


if __name__ == "__main__":
    unittest.main()
