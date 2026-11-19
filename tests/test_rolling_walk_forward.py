import math
import unittest

from strategy_family_lab import build_strategy_signals
from strategy_lab import _market_regime_diagnostics
from rolling_walk_forward import evaluate_rolling_walk_forward


class RollingWalkForwardTests(unittest.TestCase):
    def candles(self, count):
        return [[i, 100.0 + i, 101.0 + i, 99.0 + i, 100.0 + i, 1000.0]
                for i in range(count)]

    def test_expanding_training_and_contiguous_test_windows(self):
        rows = self.candles(22)
        trend = [True] * 22
        flat = [False] * 22
        result = evaluate_rolling_walk_forward(
            rows, {"trend": trend, "flat": flat},
            initial_train_bars=8, test_bars=4, fee_rate=0, slippage_rate=0,
            bars_per_year=1,
        )
        self.assertEqual(result["protocol"], "expanding_window_rolling_walk_forward_frozen_candidate")
        self.assertEqual(result["fold_count"], 3)
        self.assertEqual(
            [(f["training_end_index_exclusive"], f["test_start_index"], f["test_end_index_exclusive"])
             for f in result["folds"]],
            [(8, 8, 12), (12, 12, 16), (16, 16, 20)],
        )
        self.assertEqual(result["promotion_status"], "NO_CANDIDATE_PROMOTED")
        self.assertEqual(result["unused_tail_bars"], 1)
        self.assertEqual([f["test_strategy"]["bars"] for f in result["folds"]], [4, 4, 4])
        self.assertEqual(
            [f["test_return_start_open_index"] for f in result["folds"][1:]],
            [f["test_return_end_open_index"] for f in result["folds"][:-1]],
        )
        self.assertEqual(set(result["aggregate_oos_cost_scenarios"]), {"1x", "2x", "3x"})
        self.assertIn("period_sharpe", result["aggregate_oos_cost_scenarios"]["1x"]["strategy"])
        self.assertIn("periodic_profit_factor", result["aggregate_oos_cost_scenarios"]["1x"]["strategy"])
        self.assertTrue(all("training_closed_trades" in fold for fold in result["folds"]))
        for fold in result["folds"]:
            self.assertEqual(set(fold["cost_scenarios"]), {"1x", "2x", "3x"})
        self.assertEqual(
            result["aggregate_oos_cost_scenarios"]["1x"]["strategy"]["bars"],
            sum(fold["cost_scenarios"]["1x"]["strategy"]["bars"] for fold in result["folds"]),
        )

    def test_training_selection_uses_only_past_rows(self):
        rows = self.candles(12)
        first = [True] * 12
        second = [False] * 12
        original = evaluate_rolling_walk_forward(
            rows, {"a": first, "b": second}, 6, 3,
            fee_rate=0, slippage_rate=0, bars_per_year=1,
        )
        changed_future = rows[:6] + [
            [i, 1000.0 + i, 1001.0 + i, 999.0 + i, 1000.0 + i, 1000.0]
            for i in range(6, 12)
        ]
        altered = evaluate_rolling_walk_forward(
            changed_future, {"a": first, "b": second}, 6, 3,
            fee_rate=0, slippage_rate=0, bars_per_year=1,
        )
        self.assertEqual(
            original["folds"][0]["training_excess_returns"],
            altered["folds"][0]["training_excess_returns"],
        )
        self.assertEqual(
            original["folds"][0]["selected_candidate"],
            altered["folds"][0]["selected_candidate"],
        )

    def test_all_17_predeclared_btc_candidates_run_under_25pct_cap(self):
        rows = []
        for i in range(280):
            close = 100.0 + 0.08 * i + 3.0 * math.sin(i / 9.0)
            rows.append([i, close, close * 1.01, close * 0.99, close, 1000.0])
        signals = build_strategy_signals(rows)
        self.assertEqual(len(signals), 17)
        result = evaluate_rolling_walk_forward(
            rows, signals, initial_train_bars=220, test_bars=30,
            fee_rate=0.001, slippage_rate=0.0005,
        )
        self.assertGreaterEqual(result["fold_count"], 1)
        self.assertEqual(result["allocation_fraction"], 0.25)
        for fold in result["folds"]:
            self.assertLessEqual(fold["test_strategy"]["exposure"], 0.25)

    def test_regime_diagnostics_cover_all_17_candidates_and_are_not_pnl(self):
        rows = []
        for i in range(280):
            close = 100.0 + 0.08 * i + 3.0 * math.sin(i / 9.0)
            rows.append([i, close, close * 1.01, close * 0.99, close, 1000.0])
        signals = build_strategy_signals(rows)
        closes = [row[4] for row in rows]
        diagnostics = _market_regime_diagnostics(closes, signals, 220)
        self.assertIn("not trade-level PnL", diagnostics["measurement"])
        for regime in diagnostics["regimes"].values():
            self.assertEqual(
                set(regime["strategy_signal_diagnostics"]),
                set(signals),
            )
            self.assertIn(regime["evidence_status"], {"DESCRIPTIVE_ONLY", "INSUFFICIENT_SAMPLE"})

    def test_aggregate_benchmark_entry_cost_is_charged_once_across_folds(self):
        rows = self.candles(22)
        result = evaluate_rolling_walk_forward(
            rows, {"always": [True] * 22, "never": [False] * 22},
            initial_train_bars=8, test_bars=4,
            fee_rate=0.001, slippage_rate=0.0005, bars_per_year=1,
        )
        aggregate = result["aggregate_oos_cost_scenarios"]["1x"]
        expected_equity = 1.0
        for open_index in range(8, 20):
            gross = (101.0 + open_index) / (100.0 + open_index) - 1.0
            entry_cost = 0.0015 * 0.25 if open_index == 8 else 0.0
            expected_equity *= (1 + 0.25 * gross) * (1 - entry_cost)
        expected = expected_equity - 1.0
        self.assertAlmostEqual(aggregate["buy_and_hold"]["net_return"], expected)
        self.assertTrue(aggregate["benchmark_entry_cost_charged_once"])
        self.assertTrue(aggregate["fold_boundary_exposure_is_continuous"])

    def test_rejects_allocation_above_research_cap(self):
        rows = self.candles(12)
        for allocation in (0.250001, 1.0, True, float("nan")):
            with self.subTest(allocation=allocation):
                with self.assertRaises(ValueError):
                    evaluate_rolling_walk_forward(
                        rows, {"a": [True] * 12}, 6, 3,
                        allocation_fraction=allocation,
                    )

    def test_rejects_misaligned_or_invalid_inputs(self):
        rows = self.candles(12)
        with self.assertRaises(ValueError):
            evaluate_rolling_walk_forward(rows, {"a": [True]}, 6, 3)
        with self.assertRaises(ValueError):
            evaluate_rolling_walk_forward(rows, {"a": [1] * 12}, 6, 3)
        with self.assertRaises(ValueError):
            evaluate_rolling_walk_forward(rows, {"a": [True] * 12}, 6, 2)
        with self.assertRaises(ValueError):
            evaluate_rolling_walk_forward(rows, {"a": [True] * 12}, 12, 3)



    def test_fixed_candidate_walk_forward_evaluates_every_candidate_and_reconciles_regimes(self):
        rows = []
        for i in range(280):
            close = 100.0 + 0.08 * i + 3.0 * math.sin(i / 9.0)
            rows.append([i, close, close * 1.01, close * 0.99, close, 1000.0])
        signals = build_strategy_signals(rows)
        result = evaluate_rolling_walk_forward(
            rows, signals, initial_train_bars=220, test_bars=30,
            fee_rate=0.001, slippage_rate=0.0005,
        )
        fixed = result["fixed_candidate_walk_forward"]
        self.assertEqual(fixed["candidate_count"], 17)
        self.assertEqual(set(fixed["candidates"]), set(signals))
        self.assertEqual(fixed["fold_count"], result["fold_count"])
        for candidate in fixed["candidates"].values():
            self.assertEqual(len(candidate["folds"]), fixed["fold_count"])
            self.assertEqual(
                set(candidate["aggregate_oos_cost_scenarios"]), {"1x", "2x", "3x"}
            )
            one_x = candidate["aggregate_oos_cost_scenarios"]["1x"]["strategy"]
            self.assertEqual(
                one_x["bars"],
                sum(fold["strategy"]["bars"] for fold in candidate["folds"]),
            )
            log_contribution = sum(
                regime["net_log_contribution_pct"]
                for regime in candidate["regime_attribution"].values()
            )
            expected_log_growth = math.log1p(one_x["net_return"]) * 100.0
            self.assertAlmostEqual(log_contribution, expected_log_growth, places=8)
            self.assertIn(
                candidate["regime_attribution"]["bullish"]["evidence_status"],
                {"DESCRIPTIVE_ONLY", "INSUFFICIENT_SAMPLE"},
            )

    def test_fixed_candidate_first_fold_is_independent_of_later_test_rows(self):
        rows = self.candles(22)
        signals = {"a": [True] * 22, "b": [False] * 22}
        original = evaluate_rolling_walk_forward(
            rows, signals, 8, 4, fee_rate=0, slippage_rate=0, bars_per_year=1,
        )
        changed_later = rows[:12] + [
            [i, 500.0 + i, 501.0 + i, 499.0 + i, 500.0 + i, 1000.0]
            for i in range(12, len(rows))
        ]
        altered = evaluate_rolling_walk_forward(
            changed_later, signals, 8, 4, fee_rate=0, slippage_rate=0, bars_per_year=1,
        )
        original_first = original["fixed_candidate_walk_forward"]["candidates"]["a"]["folds"][0]
        altered_first = altered["fixed_candidate_walk_forward"]["candidates"]["a"]["folds"][0]
        self.assertEqual(
            original_first["strategy"]["net_return"],
            altered_first["strategy"]["net_return"],
        )
        self.assertEqual(
            original_first["test_start_index"],
            altered_first["test_start_index"],
        )

if __name__ == "__main__":
    unittest.main()
