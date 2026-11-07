"""Regression tests for paper execution costs and strategy comparison."""
import json
import math
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from paper_account import _ema_last, _save_state_atomically, run_paper_portfolio, update_paper_account
from paper_trading import run_backtest
from strategy_lab import _consensus_signals, _simulate, run_strategy_lab
from risk_analysis import block_bootstrap_trade_risk, monte_carlo_trade_risk


class MonteCarloRiskTests(unittest.TestCase):
    def test_bootstrap_risk_is_reproducible_and_reports_tail_risk(self):
        trades = [
            {"pnl": 12.0}, {"pnl": -8.0}, {"pnl": 15.0},
            {"pnl": -10.0}, {"pnl": 4.0}, {"pnl": -3.0},
        ]
        first = monte_carlo_trade_risk(trades, simulations=1000, seed=7)
        second = monte_carlo_trade_risk(trades, simulations=1000, seed=7)
        self.assertEqual(first, second)
        self.assertEqual(first["trade_count"], len(trades))
        self.assertEqual(first["simulations"], 1000)
        self.assertGreaterEqual(first["p95_max_drawdown_pct"], first["median_max_drawdown_pct"])
        self.assertIn("serial dependence", " ".join(first["limitations"]))

    def test_bootstrap_risk_handles_empty_trades_and_rejects_invalid_input(self):
        self.assertEqual(
            monte_carlo_trade_risk([])["status"],
            "INSUFFICIENT_TRADES",
        )
        with self.assertRaises(ValueError):
            monte_carlo_trade_risk([{"pnl": float("nan")}])
        with self.assertRaises(ValueError):
            monte_carlo_trade_risk([{"pnl": 1.0}], simulations=99)


class BlockBootstrapRiskTests(unittest.TestCase):
    def test_block_bootstrap_is_reproducible_and_reports_method(self):
        trades = [{"pnl": value} for value in [8, -12, -10, 7, 9, -11, -8, 6]]
        first = block_bootstrap_trade_risk(trades, simulations=500, seed=19, block_size=2)
        second = block_bootstrap_trade_risk(trades, simulations=500, seed=19, block_size=2)
        self.assertEqual(first, second)
        self.assertEqual(first["trade_count"], len(trades))
        self.assertEqual(first["block_size"], 2)
        self.assertIn("block", first["method"])
        self.assertGreaterEqual(first["p95_max_drawdown_pct"], first["median_max_drawdown_pct"])

    def test_block_bootstrap_validates_parameters_and_empty_input(self):
        self.assertEqual(block_bootstrap_trade_risk([])["status"], "INSUFFICIENT_TRADES")
        with self.assertRaises(ValueError):
            block_bootstrap_trade_risk([{"pnl": 1.0}], block_size=0)
        with self.assertRaises(ValueError):
            block_bootstrap_trade_risk([{"pnl": float("inf")}])



class ConsensusEnsembleTests(unittest.TestCase):
    def test_equal_family_votes_prevent_trend_family_dominance(self):
        names = (
            "sma_trend", "ema_trend", "sma200_regime", "ema50_200_regime",
            "sma200_filter", "ema200_filter", "sma50_200_cross", "donchian_55_20",
            "rsi_momentum", "rsi2_mean_reversion", "rsi14_mean_reversion",
            "bollinger_mean_reversion",
        )
        signals = {name: [False, False] for name in names}
        for name in names[:4]:
            signals[name][0] = True
        signals["rsi_momentum"][0] = True
        for name in names[:8]:
            signals[name][1] = True
        self.assertEqual(_consensus_signals(signals), [True, False])

    def test_consensus_requires_two_mean_reversion_votes_and_valid_lengths(self):
        names = (
            "sma_trend", "ema_trend", "sma200_regime", "ema50_200_regime",
            "sma200_filter", "ema200_filter", "sma50_200_cross", "donchian_55_20",
            "rsi_momentum", "rsi2_mean_reversion", "rsi14_mean_reversion",
            "bollinger_mean_reversion",
        )
        signals = {name: [False] for name in names}
        signals["rsi_momentum"] = [True]
        signals["rsi2_mean_reversion"] = [True]
        signals["rsi14_mean_reversion"] = [True]
        self.assertEqual(_consensus_signals(signals), [True])
        signals["ema_trend"] = [True, False]
        with self.assertRaises(ValueError):
            _consensus_signals(signals)


class StrategyLabTests(unittest.TestCase):
    def test_benchmark_reports_drawdown_and_liquidation_costs(self):
        prices = [100.0 + i * 0.2 for i in range(180)]
        report = run_strategy_lab(prices)
        benchmark = report["strategies"]["buy_and_hold"]["out_of_sample"]
        self.assertIsInstance(benchmark["max_drawdown_pct"], float)
        self.assertFalse(benchmark["open_position"])
        self.assertTrue(benchmark["fees_and_slippage_included"])
        self.assertEqual(benchmark["allocation_fraction"], 0.25)
        for name in ("sma_trend", "ema_trend", "rsi_momentum", "sma200_regime", "ema50_200_regime", "sma200_filter", "ema200_filter", "sma50_200_cross", "donchian_55_20", "rsi2_mean_reversion", "rsi14_mean_reversion", "bollinger_mean_reversion"):
            strategy = report["strategies"][name]
            self.assertEqual(len(strategy["walk_forward_windows"]), 3)
            self.assertTrue(all(
                window["start_index"] >= report["split_index"]
                for window in strategy["walk_forward_windows"]
            ))
            self.assertIsNotNone(strategy["worst_window_return_pct"])
        self.assertLess(benchmark["final_equity_usd"], 1000.0 * prices[-1] / prices[int(len(prices) * 0.7)])

    def test_benchmark_drawdown_includes_estimated_exit_costs(self):
        prices = [100.0] * 180
        report = run_strategy_lab(prices)
        benchmark = report["strategies"]["buy_and_hold"]["out_of_sample"]

        allocation = 250.0
        fee = 0.001
        slippage = 0.0005
        units = (allocation - allocation * fee) / (100.0 * (1 + slippage))
        liquidation = units * 100.0 * (1 - slippage)
        liquidation -= liquidation * fee
        net_equity = 750.0 + liquidation
        expected_drawdown = (1000.0 - net_equity) / 1000.0 * 100.0
        self.assertAlmostEqual(
            benchmark["max_drawdown_pct"], expected_drawdown, places=2
        )

    def test_open_strategy_position_uses_net_liquidation_value(self):
        prices = [100.0 + i * 0.5 for i in range(180)]
        report = run_strategy_lab(prices)
        for name in ("sma_trend", "ema_trend", "rsi_momentum", "sma200_regime"):
            metrics = report["strategies"][name]["out_of_sample"]
            self.assertTrue(math.isfinite(metrics["final_equity_usd"]))
            self.assertGreaterEqual(metrics["max_drawdown_pct"], 0.0)

    def test_strategy_drawdown_includes_open_position_liquidation_costs(self):
        prices = [100.0] * 8
        signals = [True] * 8
        fee = 0.01
        slippage = 0.01
        metrics = _simulate(prices, signals, 1, len(prices), fee, slippage)

        units = (250.0 - 250.0 * fee) / (100.0 * (1.0 + slippage))
        net_liquidation = 750.0 + units * 100.0 * (1.0 - slippage) * (1.0 - fee)
        expected_drawdown = (1000.0 - net_liquidation) / 1000.0 * 100.0
        self.assertAlmostEqual(metrics["max_drawdown_pct"], expected_drawdown, places=2)

    def test_rejects_boolean_and_non_finite_prices(self):
        with self.assertRaises(ValueError):
            run_strategy_lab([100.0] * 119 + [True])
        with self.assertRaises(ValueError):
            run_strategy_lab([100.0] * 119 + [float("nan")])

    def test_backtest_drawdown_includes_open_position_liquidation_costs(self):
        prices = [float(value) for value in range(50, 100)] + [100.0, 50.0]
        fee = 0.01
        slippage = 0.02
        report = run_backtest(prices, fee_rate=fee, slippage_rate=slippage)

        units = (1000.0 - 1000.0 * fee) / (100.0 * (1.0 + slippage))
        expected_equity = units * 50.0 * (1.0 - slippage) * (1.0 - fee)
        expected_drawdown = (1000.0 - expected_equity) / 1000.0 * 100.0
        self.assertAlmostEqual(report["max_drawdown_pct"], expected_drawdown, places=2)

    def test_backtest_open_position_includes_estimated_exit_costs(self):
        prices = [100.0 + i * 0.5 for i in range(100)]
        report = run_backtest(prices)
        self.assertTrue(report["open_position"])
        self.assertTrue(report["estimated_liquidation_value"])
        self.assertLess(report["final_equity_usd"], 1000.0 * prices[-1] / prices[50])


class PersistentPaperAccountTests(unittest.TestCase):
    def make_candles(self, prices):
        return [[i * 3600, "0", "0", "0", str(price)] for i, price in enumerate(prices)]

    def test_atomic_state_write_preserves_existing_file_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "paper_state.json"
            target.write_text("previous-valid-state\\n", encoding="utf-8")
            with patch("paper_account.os.replace", side_effect=OSError("simulated replace failure")):
                with self.assertRaises(OSError):
                    _save_state_atomically(target, {"version": 1})
            self.assertEqual(target.read_text(encoding="utf-8"), "previous-valid-state\\n")
            self.assertEqual(list(Path(folder).glob(".paper_state.json.*.tmp")), [])

    def test_rejects_inconsistent_persisted_position_and_risk_state(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "paper_state.json"
            candles = self.make_candles([100.0 + i for i in range(55)])
            update_paper_account(candles, state_path=str(state_path))
            original = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertGreater(original["btc"], 0)
            corruptions = []
            flat_with_entry_cost = json.loads(json.dumps(original))
            flat_with_entry_cost["btc"] = 0.0
            corruptions.append(flat_with_entry_cost)
            open_without_entry_cost = json.loads(json.dumps(original))
            open_without_entry_cost["entry_cost"] = 0.0
            corruptions.append(open_without_entry_cost)
            excessive_drawdown = json.loads(json.dumps(original))
            excessive_drawdown["max_drawdown_pct"] = 101.0
            corruptions.append(excessive_drawdown)
            zero_daily_equity = json.loads(json.dumps(original))
            zero_daily_equity["daily_start_equity"] = 0.0
            corruptions.append(zero_daily_equity)
            for index, corrupted in enumerate(corruptions):
                state_path.write_text(json.dumps(corrupted), encoding="utf-8")
                with self.subTest(corruption=index):
                    with self.assertRaises(ValueError):
                        update_paper_account(candles, state_path=str(state_path))

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

    def test_daily_bollinger_paper_account_enters_and_exits_on_reversion(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = str(Path(folder) / "bollinger.json")
            prices = [100.0 + i for i in range(200)] + [250.0, 251.0, 290.0, 295.0]
            candles = [
                [i * 86400, "0", "0", "0", str(price)]
                for i, price in enumerate(prices)
            ]
            result = update_paper_account(
                candles,
                state_path=state_path,
                strategy="bollinger_mean_reversion",
            )
            self.assertEqual(result["completed_trades"], 1)
            self.assertFalse(result["open_position"])
            self.assertGreater(result["return_pct"], 0)
            saved = json.loads(Path(state_path).read_text(encoding="utf-8"))
            self.assertEqual(saved["holding_bars"], 0)

    def test_six_hour_rsi14_paper_account_enters_and_exits_on_rebound(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = str(Path(folder) / "rsi14.json")
            prices = [100.0 + i for i in range(200)]
            prices += [294.0 - 5.0 * i for i in range(14)]
            prices += [234.0 + 5.0 * i for i in range(15)]
            candles = [
                [i * 6 * 3600, "0", "0", "0", str(price)]
                for i, price in enumerate(prices)
            ]
            result = update_paper_account(
                candles,
                state_path=state_path,
                strategy="rsi14_mean_reversion",
            )
            self.assertGreaterEqual(result["completed_trades"], 1)
            self.assertFalse(result["open_position"])
            self.assertGreater(result["return_pct"], 0)

    def test_five_consecutive_losses_trigger_persistent_pause_and_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "loss_streak.json"
            candles = self.make_candles([100.0 + i for i in range(55)])
            update_paper_account(candles, state_path=str(state_path))
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            saved["trades"] = [
                {"pnl_usd": -1.0, "result": "LOSS", "side": "SELL"}
                for _ in range(5)
            ]
            saved["btc"] = 0.01
            saved["entry_cost"] = 1.0
            saved["cash"] = 999.0
            saved["last_timestamp"] = 54 * 3600
            state_path.write_text(json.dumps(saved), encoding="utf-8")
            next_candle = self.make_candles([100.0 + i for i in range(55)] + [155.0])
            result = update_paper_account(next_candle, state_path=str(state_path))
            self.assertTrue(result["paused_for_loss_streak"])
            self.assertFalse(result["open_position"])
            self.assertEqual(result["risk_limits"]["max_consecutive_losses"], 5)

    def test_existing_loss_streak_is_reconciled_without_new_candles(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "legacy_streak.json"
            candles = self.make_candles([100.0 + i for i in range(55)])
            update_paper_account(candles, state_path=str(state_path))
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            saved["trades"] = [
                {"pnl_usd": -2.0, "result": "LOSS", "side": "SELL"}
                for _ in range(6)
            ]
            state_path.write_text(json.dumps(saved), encoding="utf-8")
            result = update_paper_account(candles, state_path=str(state_path))
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(result["processed_new_candles"], 0)
            self.assertTrue(result["paused_for_loss_streak"])
            self.assertTrue(persisted["paused_for_loss_streak"])

    def test_report_distinguishes_current_and_historical_loss_streaks(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "streak_report.json"
            candles = self.make_candles([100.0 + i for i in range(55)])
            update_paper_account(candles, state_path=str(state_path))
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            saved["trades"] = [
                {"pnl_usd": -1.0, "result": "LOSS", "side": "SELL"}
                for _ in range(6)
            ] + [{"pnl_usd": 2.0, "result": "WIN", "side": "SELL"},
                 {"pnl_usd": -0.5, "result": "LOSS", "side": "SELL"}]
            state_path.write_text(json.dumps(saved), encoding="utf-8")
            result = update_paper_account(candles, state_path=str(state_path))
            self.assertEqual(result["max_consecutive_losses"], 6)
            self.assertEqual(result["current_consecutive_losses"], 1)
            self.assertEqual(result["risk_pause_reasons"], [])

    def test_daily_loss_guard_uses_previous_completed_candle(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = str(Path(folder) / "daily_loss.json")
            rising = self.make_candles([100.0 + i for i in range(55)])
            update_paper_account(rising, state_path=state_path)
            next_day = [72 * 3600, "0", "0", "0", "135"]
            result = update_paper_account(rising + [next_day], state_path=state_path)
            self.assertTrue(result["daily_loss_paused"])
            self.assertFalse(result["paused_for_drawdown"])
            self.assertFalse(result["open_position"])

    def test_three_independent_paper_strategy_ledgers(self):
        with tempfile.TemporaryDirectory() as folder:
            candles = self.make_candles([100.0 + (i % 40) * 0.4 for i in range(180)])
            first = run_paper_portfolio(candles, state_dir=folder)
            second = run_paper_portfolio(candles, state_dir=folder)
            self.assertEqual(set(first["accounts"]), {"sma_trend", "ema_trend", "rsi_momentum", "sma200_regime", "ema50_200_regime"})
            for name, account in second["accounts"].items():
                self.assertEqual(account["processed_new_candles"], 0)
                self.assertEqual(account["strategy"], name)
                self.assertTrue(account["state_persisted"])

    def test_sma200_strategy_retains_200_candle_warmup(self):
        with tempfile.TemporaryDirectory() as folder:
            candles = self.make_candles([100.0 + (i % 250) * 0.1 for i in range(260)])
            result = update_paper_account(
                candles,
                state_path=str(Path(folder) / "sma200.json"),
                strategy="sma200_regime",
            )
            saved = json.loads((Path(folder) / "sma200.json").read_text(encoding="utf-8"))
            self.assertEqual(result["processed_new_candles"], 260)
            self.assertEqual(len(saved["recent_closes"]), 200)
            self.assertEqual(result["strategy"], "sma200_regime")

    def test_ema200_paper_strategy_preserves_full_signal_history(self):
        with tempfile.TemporaryDirectory() as folder:
            candles = self.make_candles([100.0 + (i % 70) * 0.5 for i in range(260)])
            path = Path(folder) / "ema200.json"
            update_paper_account(candles, state_path=str(path), strategy="ema50_200_regime")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["recent_closes"]), 260)
            prices = [100.0 + (i % 70) * 0.5 for i in range(260)]
            self.assertAlmostEqual(saved["ema50_state"], _ema_last(prices, 50), places=10)
            self.assertAlmostEqual(saved["ema200_state"], _ema_last(prices, 200), places=10)

    def test_corrupt_state_is_not_silently_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "paper_state.json"
            state_path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                update_paper_account(self.make_candles([100.0 + i for i in range(55)]),
                                     state_path=str(state_path))

    def test_rejects_corrupt_persisted_trade_and_risk_state(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "paper_state.json"
            candles = self.make_candles([100.0 + i for i in range(55)])
            update_paper_account(candles, state_path=str(state_path))

            original = json.loads(state_path.read_text(encoding="utf-8"))
            corruptions = []
            bad_trade = json.loads(json.dumps(original))
            bad_trade["trades"] = [{
                "pnl_usd": float("nan"), "side": "SELL", "result": "LOSS"
            }]
            corruptions.append(bad_trade)

            bad_flag = json.loads(json.dumps(original))
            bad_flag["paused_for_drawdown"] = "false"
            corruptions.append(bad_flag)

            bad_initial_cash = json.loads(json.dumps(original))
            bad_initial_cash["initial_cash"] = True
            corruptions.append(bad_initial_cash)

            for index, corrupted in enumerate(corruptions):
                state_path.write_text(json.dumps(corrupted), encoding="utf-8")
                with self.subTest(corruption=index):
                    with self.assertRaises(ValueError):
                        update_paper_account(
                            candles,
                            state_path=str(state_path),
                        )

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
