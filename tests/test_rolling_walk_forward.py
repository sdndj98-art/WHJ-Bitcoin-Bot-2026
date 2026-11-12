import math
import unittest

from strategy_family_lab import build_strategy_signals
from rolling_walk_forward import evaluate_rolling_walk_forward


class RollingWalkForwardTests(unittest.TestCase):
    def candles(self, count):
        return [[i, 100.0 + i, 101.0 + i, 99.0 + i, 100.0 + i, 1000.0]
                for i in range(count)]

    def test_expanding_training_and_contiguous_test_windows(self):
        rows = self.candles(20)
        trend = [True] * 20
        flat = [False] * 20
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
        self.assertEqual(result["unused_tail_bars"], 0)
        self.assertEqual(set(result["aggregate_oos_cost_scenarios"]), {"1x", "2x", "3x"})
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


if __name__ == "__main__":
    unittest.main()
