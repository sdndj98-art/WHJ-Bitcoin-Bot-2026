"""Regression tests for paper execution costs and strategy comparison."""
import math
import unittest

from paper_trading import run_backtest
from strategy_lab import run_strategy_lab


class StrategyLabTests(unittest.TestCase):
    def test_benchmark_reports_drawdown_and_liquidation_costs(self):
        prices = [100.0 + i * 0.2 for i in range(180)]
        report = run_strategy_lab(prices)
        benchmark = report["strategies"]["buy_and_hold"]["out_of_sample"]
        self.assertIsInstance(benchmark["max_drawdown_pct"], float)
        self.assertFalse(benchmark["open_position"])
        self.assertTrue(benchmark["fees_and_slippage_included"])
        self.assertLess(benchmark["final_equity_usd"], 1000.0 * prices[-1] / prices[int(len(prices) * 0.7)])

    def test_open_strategy_position_uses_net_liquidation_value(self):
        prices = [100.0 + i * 0.5 for i in range(180)]
        report = run_strategy_lab(prices)
        for name in ("sma_trend", "ema_trend", "rsi_momentum"):
            metrics = report["strategies"][name]["out_of_sample"]
            self.assertTrue(math.isfinite(metrics["final_equity_usd"]))
            self.assertGreaterEqual(metrics["max_drawdown_pct"], 0.0)

    def test_rejects_boolean_and_non_finite_prices(self):
        with self.assertRaises(ValueError):
            run_strategy_lab([100.0] * 119 + [True])
        with self.assertRaises(ValueError):
            run_strategy_lab([100.0] * 119 + [float("nan")])

    def test_backtest_open_position_includes_estimated_exit_costs(self):
        prices = [100.0 + i * 0.5 for i in range(100)]
        report = run_backtest(prices)
        self.assertTrue(report["open_position"])
        self.assertTrue(report["estimated_liquidation_value"])
        self.assertLess(report["final_equity_usd"], 1000.0 * prices[-1] / prices[50])


if __name__ == "__main__":
    unittest.main()
