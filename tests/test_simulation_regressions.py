"""Regression tests for paper execution costs and strategy comparison."""
import json
import math
import tempfile
import unittest
from pathlib import Path

from paper_account import run_paper_portfolio, update_paper_account
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
        for name in ("sma_trend", "ema_trend", "rsi_momentum"):
            strategy = report["strategies"][name]
            self.assertEqual(len(strategy["walk_forward_windows"]), 3)
            self.assertIsNotNone(strategy["worst_window_return_pct"])
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


class PersistentPaperAccountTests(unittest.TestCase):
    def make_candles(self, prices):
        return [[i * 3600, "0", "0", "0", str(price)] for i, price in enumerate(prices)]

    def test_state_persists_and_reprocessing_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = str(Path(folder) / "paper_state.json")
            candles = self.make_candles([100.0 + i for i in range(55)])
            first = update_paper_account(candles, state_path=state_path)
            second = update_paper_account(candles, state_path=state_path)
            self.assertEqual(first["processed_new_candles"], 55)
            self.assertEqual(second["processed_new_candles"], 0)
            self.assertEqual(first["equity_after_estimated_exit_costs_usd"],
                             second["equity_after_estimated_exit_costs_usd"])
            self.assertTrue(Path(state_path).exists())
            self.assertIn("max_drawdown_pct", first)
            self.assertIn("win_rate_pct", first)
            self.assertTrue(second["state_persisted"])

    def test_drawdown_guard_pauses_and_forces_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = str(Path(folder) / "paper_state.json")
            rising = self.make_candles([100.0 + i for i in range(55)])
            update_paper_account(rising, state_path=state_path)
            falling = self.make_candles([100.0 + i for i in range(55)] + [80.0, 79.0])
            result = update_paper_account(falling, state_path=state_path)
            self.assertTrue(result["paused_for_drawdown"])
            self.assertGreaterEqual(result["max_drawdown_pct"], 10.0)
            self.assertFalse(result["open_position"])
            self.assertGreaterEqual(result["completed_trades"], 1)

    def test_three_independent_paper_strategy_ledgers(self):
        with tempfile.TemporaryDirectory() as folder:
            candles = self.make_candles([100.0 + (i % 40) * 0.4 for i in range(180)])
            first = run_paper_portfolio(candles, state_dir=folder)
            second = run_paper_portfolio(candles, state_dir=folder)
            self.assertEqual(set(first["accounts"]), {"sma_trend", "ema_trend", "rsi_momentum", "sma200_regime"})
            for name, account in second["accounts"].items():
                self.assertEqual(account["processed_new_candles"], 0)
                self.assertEqual(account["strategy"], name)
                self.assertTrue(account["state_persisted"])

    def test_corrupt_state_is_not_silently_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "paper_state.json"
            state_path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                update_paper_account(self.make_candles([100.0 + i for i in range(55)]),
                                     state_path=str(state_path))

    def test_rejects_invalid_cash_and_fractional_timestamps(self):
        candles = self.make_candles([100.0 + i for i in range(55)])
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                update_paper_account(candles, state_path=str(Path(folder) / "cash.json"),
                                     initial_cash=0)
            candles[10][0] = 10.5
            with self.assertRaises(ValueError):
                update_paper_account(candles, state_path=str(Path(folder) / "time.json"))

    def test_rejects_duplicate_or_unsorted_timestamps(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = str(Path(folder) / "paper_state.json")
            candles = self.make_candles([100.0 + i for i in range(55)])
            candles[-1][0] = candles[-2][0]
            with self.assertRaises(ValueError):
                update_paper_account(candles, state_path=state_path)


if __name__ == "__main__":
    unittest.main()
