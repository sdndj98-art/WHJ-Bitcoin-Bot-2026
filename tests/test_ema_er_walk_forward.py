import copy
import math
import unittest
from datetime import datetime, timezone

from ema_er_walk_forward import (
    THRESHOLDS,
    _select_threshold,
    run_er_expanding_walk_forward,
)


def hourly_candles(count=7200):
    rows = []
    previous = 10000.0
    for index in range(count):
        # A deterministic mixture of drift and cycles creates both trend and chop.
        close = 10000.0 + index * 0.12 + 180.0 * math.sin(index / 37.0) + 65.0 * math.sin(index / 9.0)
        open_price = previous
        rows.append({
            "timestamp": index * 3600000,
            "open": open_price,
            "high": max(open_price, close) + 3.0,
            "low": min(open_price, close) - 3.0,
            "close": close,
            "volume": 10.0,
            "imputed": False,
        })
        previous = close
    return rows


def metrics(return_pct, drawdown, trades=20, profit_factor=1.2):
    return {
        "return_pct": return_pct,
        "max_drawdown_pct": drawdown,
        "closed_trades": trades,
        "profit_factor": profit_factor,
    }


class ExpandingERWalkForwardTests(unittest.TestCase):
    def test_selection_uses_only_training_metrics_and_keeps_baseline_when_weaker(self):
        baseline = metrics(5.0, 3.0)
        candidates = {str(value): metrics(4.0, 3.0) for value in THRESHOLDS}
        selected, rule = _select_threshold(candidates, baseline)
        self.assertIsNone(selected)
        self.assertEqual(rule, "TRAINING_ONLY_BASELINE_OUTSCORES_ER")

        candidates["0.35"] = metrics(8.0, 2.0)
        selected, rule = _select_threshold(candidates, baseline)
        self.assertEqual(selected, 0.35)
        self.assertEqual(rule, "TRAINING_ONLY_ER_SCORE_BEATS_BASELINE")

    def test_no_eligible_candidate_falls_back_to_baseline(self):
        candidates = {str(value): metrics(20.0, 1.0, trades=4) for value in THRESHOLDS}
        selected, rule = _select_threshold(candidates, metrics(2.0, 2.0))
        self.assertIsNone(selected)
        self.assertEqual(rule, "TRAINING_ONLY_BASELINE_NO_ELIGIBLE_ER_SAMPLE")

    def test_walk_forward_reports_three_independent_paper_free_folds(self):
        report = run_er_expanding_walk_forward(hourly_candles())
        self.assertEqual(report["mode"], "EXPANDING_WINDOW_ER20_ENTRY_ONLY_WALK_FORWARD")
        self.assertTrue(report["research_only"])
        self.assertFalse(report["paper_state_touched"])
        self.assertFalse(report["live_orders_enabled"])
        self.assertTrue(report["no_same_fold_test_feedback"])
        self.assertEqual(len(report["folds"]), 3)
        for fold in report["folds"]:
            self.assertLess(fold["training_end_exclusive_utc"], fold["test_start_utc"])
            self.assertIn(fold["selected_threshold"], [None, *THRESHOLDS])
            self.assertIn("selected_strategy", fold["test"])
            self.assertIn("baseline_ema50_200", fold["test"])
            self.assertIn("matched_buy_and_hold_50_50", fold["test"])
            self.assertIn("selected_strategy_2x_cost", fold["test"])

    def test_perturbing_first_test_fold_cannot_change_its_training_or_selection(self):
        original = hourly_candles()
        first = run_er_expanding_walk_forward(original)
        test_start = datetime.fromisoformat(first["folds"][0]["test_start_utc"]).timestamp() * 1000
        changed = copy.deepcopy(original)
        for row in changed:
            if row["timestamp"] >= test_start:
                for field in ("open", "high", "low", "close"):
                    row[field] *= 1.35
        second = run_er_expanding_walk_forward(changed)
        self.assertEqual(
            first["folds"][0]["selected_threshold"],
            second["folds"][0]["selected_threshold"],
        )
        self.assertEqual(
            first["folds"][0]["training_metrics_by_threshold"],
            second["folds"][0]["training_metrics_by_threshold"],
        )

    def test_rejects_invalid_costs_and_fold_configuration(self):
        candles = hourly_candles(2400)
        with self.assertRaisesRegex(ValueError, "Fee and slippage"):
            run_er_expanding_walk_forward(candles, fee=float("nan"))
        with self.assertRaisesRegex(ValueError, "At least two"):
            run_er_expanding_walk_forward(candles, folds=1)


if __name__ == "__main__":
    unittest.main()
