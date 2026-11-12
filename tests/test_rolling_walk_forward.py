import unittest

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
