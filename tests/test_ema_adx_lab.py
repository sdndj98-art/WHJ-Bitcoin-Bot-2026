import math
import unittest

from ema_adx_lab import _adx_entry_only_filter, run_ema_adx_filter_lab


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

    def test_lab_reports_fixed_thresholds_and_preserves_safety(self):
        report = run_ema_adx_filter_lab(hourly_candles())
        self.assertEqual(report["mode"], "EMA50_200_4H_6H_50_50_ADX_ENTRY_CONFIRMATION_RESEARCH")
        self.assertTrue(report["research_only"])
        self.assertFalse(report["paper_state_touched"])
        self.assertFalse(report["live_orders_enabled"])
        self.assertEqual(report["thresholds_tested"], [15.0, 20.0, 25.0])
        self.assertEqual(set(report["cost_sensitivity"]), {"1x", "2x"})
        self.assertEqual(len(report["walk_forward_windows"]["adx_20_entry_only"]), 3)
        self.assertEqual(len(report["walk_forward_windows"]["baseline"]), 3)
        self.assertEqual(len(report["walk_forward_windows"]["matched_benchmark"]), 3)
        self.assertEqual(len(report["walk_forward_cost_sensitivity"]["2x"]["baseline"]), 3)
        self.assertEqual(
            len(report["walk_forward_cost_sensitivity"]["2x"]["adx_15_entry_only"]), 3
        )
        self.assertIn("baseline", report["out_of_sample"])
        self.assertIn("matched_50_50_benchmark", report["out_of_sample"])


if __name__ == "__main__":
    unittest.main()
