import math
import unittest

from ema_adx_lab import _adx_entry_only_filter, _build_sleeve_signals, run_ema_adx_filter_lab


def hourly_candles(count=3000):
    rows = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + index * 0.03 + 3.0 * math.sin(index / 23.0)
        open_price = previous
        rows.append({
            "timestamp": index * 3600000,
            "open": open_price,
            "high": max(open_price, close) + 0.6,
            "low": min(open_price, close) - 0.6,
            "close": close,
            "volume": 10.0,
            "imputed": False,
        })
        previous = close
    return rows


class EmaAdxLabTests(unittest.TestCase):
    def test_adx_filter_authorizes_entry_but_does_not_force_exit(self):
        result = _adx_entry_only_filter(
            [False, True, True, True, False],
            [None, 15.0, 25.0, 10.0, 40.0],
            [None, 30.0, 35.0, 30.0, 40.0],
            [None, 20.0, 15.0, 20.0, 10.0],
            20.0,
        )
        self.assertEqual(result, [False, False, True, True, False])

    def test_adx_filter_rejects_malformed_inputs(self):
        with self.assertRaisesRegex(ValueError, "equal length"):
            _adx_entry_only_filter([True], [20.0], [], [1.0], 20.0)
        with self.assertRaisesRegex(ValueError, "threshold"):
            _adx_entry_only_filter([True], [20.0], [2.0], [1.0], 0.0)
        with self.assertRaisesRegex(ValueError, "threshold"):
            _adx_entry_only_filter([True], [20.0], [2.0], [1.0], True)

    def test_sleeve_signals_are_prefix_causal(self):
        bars = hourly_candles(1800)
        native = []
        for index in range(0, len(bars) - 5, 4):
            group = bars[index:index + 4]
            if len(group) != 4:
                continue
            native.append({
                "timestamp": group[0]["timestamp"],
                "open": group[0]["open"],
                "high": max(row["high"] for row in group),
                "low": min(row["low"] for row in group),
                "close": group[-1]["close"],
                "volume": sum(row["volume"] for row in group),
                "imputed": any(row["imputed"] for row in group),
            })
        full_baseline, full_confirmed = _build_sleeve_signals(native, 20.0)
        cutoff = len(native) - 30
        prefix_baseline, prefix_confirmed = _build_sleeve_signals(native[:cutoff], 20.0)
        self.assertEqual(prefix_baseline, full_baseline[:cutoff])
        self.assertEqual(prefix_confirmed, full_confirmed[:cutoff])

    def test_lab_reports_fixed_thresholds_and_preserves_safety(self):
        report = run_ema_adx_filter_lab(hourly_candles())
        self.assertEqual(report["mode"], "EMA50_200_4H_6H_50_50_ADX_ENTRY_CONFIRMATION_RESEARCH")
        self.assertTrue(report["research_only"])
        self.assertFalse(report["paper_state_touched"])
        self.assertFalse(report["live_orders_enabled"])
        self.assertEqual(report["thresholds_tested"], [15.0, 20.0, 25.0])
        self.assertFalse(report["walk_forward_retrained"])
        self.assertEqual(
            report["walk_forward_semantics"],
            "FIXED_RULE_OOS_SUBPERIOD_DIAGNOSTICS_NO_RETRAINING",
        )
        self.assertEqual(
            report["temporal_subperiod_windows"],
            report["walk_forward_windows"],
        )
        self.assertIn("not a retrained walk-forward test", report["interpretation"])
        self.assertEqual(set(report["cost_sensitivity"]), {"1x", "2x"})
        self.assertEqual(len(report["walk_forward_windows"]["adx_20_entry_only"]), 3)
        self.assertEqual(len(report["walk_forward_windows"]["baseline"]), 3)
        self.assertEqual(len(report["walk_forward_windows"]["matched_benchmark"]), 3)
        self.assertEqual(len(report["walk_forward_cost_sensitivity"]["2x"]["baseline"]), 3)
        self.assertEqual(
            len(report["walk_forward_cost_sensitivity"]["2x"]["matched_benchmark"]), 3
        )
        self.assertEqual(
            len(report["walk_forward_cost_sensitivity"]["2x"]["adx_15_entry_only"]), 3
        )
        self.assertIn("baseline", report["out_of_sample"])
        self.assertIn("matched_50_50_benchmark", report["out_of_sample"])
        robustness = report["walk_forward_robustness"]["adx_15_entry_only"]
        self.assertEqual(robustness["fold_count"], 3)
        self.assertLessEqual(robustness["positive_return_folds"], 3)
        self.assertLessEqual(robustness["outperformed_baseline_return_folds"], 3)
        self.assertLessEqual(robustness["outperformed_benchmark_return_folds"], 3)
        self.assertLessEqual(robustness["positive_return_2x_cost_folds"], 3)
        self.assertLessEqual(
            robustness["outperformed_benchmark_return_2x_cost_folds"], 3
        )


if __name__ == "__main__":
    unittest.main()
