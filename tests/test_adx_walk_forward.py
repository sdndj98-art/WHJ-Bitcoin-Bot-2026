import math
import unittest

from adx_walk_forward import _select_threshold, run_expanding_walk_forward


def synthetic_hourly(count=24 * 1000):
    rows = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + index * 0.012 + 2.0 * math.sin(index / 31.0)
        open_price = previous
        rows.append({
            "timestamp": index * 3_600_000,
            "open": open_price,
            "high": max(open_price, close) + 0.5,
            "low": min(open_price, close) - 0.5,
            "close": close,
            "volume": 5.0,
            "imputed": False,
        })
        previous = close
    return rows


class AdxWalkForwardTests(unittest.TestCase):
    def test_selection_uses_only_training_metrics_and_has_fixed_fallback(self):
        metrics = {
            "15": {"return_pct": 8.0, "max_drawdown_pct": 6.0, "closed_trades": 20, "profit_factor": 1.5},
            "20": {"return_pct": 7.0, "max_drawdown_pct": 4.0, "closed_trades": 20, "profit_factor": 1.4},
            "25": {"return_pct": 3.0, "max_drawdown_pct": 2.0, "closed_trades": 20, "profit_factor": 1.2},
        }
        selected, rule = _select_threshold(metrics)
        self.assertEqual(selected, 20.0)
        self.assertIn("TRAINING_ONLY", rule)
        sparse = {key: {**value, "closed_trades": 0} for key, value in metrics.items()}
        self.assertEqual(
            _select_threshold(sparse),
            (20.0, "DEFAULT_PRIMARY_INSUFFICIENT_TRAINING_TRADES"),
        )

    def test_selection_rejects_malformed_training_metrics(self):
        with self.assertRaisesRegex(ValueError, "exactly"):
            _select_threshold({"15": {}, "20": {}})
        with self.assertRaisesRegex(ValueError, "return"):
            _select_threshold({
                "15": {"return_pct": float("nan"), "max_drawdown_pct": 1, "closed_trades": 10},
                "20": {"return_pct": 1, "max_drawdown_pct": 1, "closed_trades": 10},
                "25": {"return_pct": 1, "max_drawdown_pct": 1, "closed_trades": 10},
            })

    def test_walk_forward_windows_are_chronological_and_training_precedes_test(self):
        report = run_expanding_walk_forward(synthetic_hourly(), folds=3)
        self.assertEqual(report["mode"], "EXPANDING_WINDOW_ADX_THRESHOLD_WALK_FORWARD")
        self.assertTrue(report["research_only"])
        self.assertFalse(report["paper_state_touched"])
        self.assertFalse(report["live_orders_enabled"])
        self.assertTrue(report["no_same_fold_test_feedback"])
        self.assertEqual(len(report["folds"]), 3)
        previous_test_end = None
        for fold in report["folds"]:
            self.assertLessEqual(
                fold["training_end_exclusive_utc"], fold["test_start_utc"]
            )
            self.assertEqual(
                fold["training_end_exclusive_utc"], fold["test_start_utc"]
            )
            if previous_test_end is not None:
                self.assertEqual(
                    fold["training_start_utc"],
                    report["folds"][0]["training_start_utc"],
                )
                self.assertGreaterEqual(
                    fold["training_end_exclusive_utc"], previous_test_end
                )
            self.assertIn(fold["selected_threshold"], (15.0, 20.0, 25.0))
            self.assertIn("selected_strategy", fold["test"])
            self.assertIn("selected_strategy_2x_cost", fold["test"])
            previous_test_end = fold["test_end_exclusive_utc"]


if __name__ == "__main__":
    unittest.main()
