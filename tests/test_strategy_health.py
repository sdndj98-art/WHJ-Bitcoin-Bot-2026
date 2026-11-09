import unittest

from strategy_health import evaluate_strategy_health


class StrategyHealthTests(unittest.TestCase):
    def test_small_sample_is_not_labeled_healthy(self):
        result = evaluate_strategy_health([2, -1, 3])
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")
        self.assertFalse(result["live_trading_approved"])

    def test_critical_drawdown_overrides_small_sample(self):
        result = evaluate_strategy_health([1, -1], [100, 90, 87])
        self.assertEqual(result["status"], "STOP_REVIEW")
        self.assertAlmostEqual(result["max_drawdown_pct"], 13.0)

    def test_recent_weakness_triggers_stop_review(self):
        trades = [2.0] * 20 + [-2.0] * 20
        result = evaluate_strategy_health(trades, min_trades=20, recent_window=20)
        self.assertEqual(result["status"], "STOP_REVIEW")
        self.assertEqual(result["recent_profit_factor"], 0.0)

    def test_drawdown_warning_triggers_watch(self):
        trades = [2.0, -1.0] * 12
        result = evaluate_strategy_health(trades, [100, 96, 92], min_trades=20)
        self.assertEqual(result["status"], "WATCH")

    def test_no_losses_is_reported_as_unbounded_not_infinity(self):
        result = evaluate_strategy_health([1, 2, 3], min_trades=3)
        self.assertIsNone(result["profit_factor"])
        self.assertTrue(result["profit_factor_unbounded"])
        self.assertEqual(result["status"], "OBSERVATION_OK")

    def test_accepts_trade_records(self):
        result = evaluate_strategy_health(
            [{"pnl": 3}, {"pnl": -1}, {"pnl": 2}],
            min_trades=3,
        )
        self.assertEqual(result["wins"], 2)
        self.assertEqual(result["losses"], 1)
        self.assertAlmostEqual(result["profit_factor"], 5.0)

    def test_rejects_non_finite_trade_and_equity(self):
        with self.assertRaises(ValueError):
            evaluate_strategy_health([float("nan")])
        with self.assertRaises(ValueError):
            evaluate_strategy_health([1], [100, float("inf")])

    def test_rejects_invalid_thresholds(self):
        with self.assertRaises(ValueError):
            evaluate_strategy_health([1], drawdown_warning_pct=12, drawdown_critical_pct=8)


if __name__ == "__main__":
    unittest.main()
